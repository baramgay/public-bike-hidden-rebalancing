"""Leakage-safe daily station forecasts with calendar/weather context and a frozen test.

Inputs are aggregate Parquet plus public KASI calendar and KMA ASOS 155 weather. No raw
trips, station geometry or end-of-year operating status are model inputs. Calendar and
weather observed before the D 00:00 cutoff are known when the forecast is made. Same-day
observed weather is an ORACLE stand-in for a perfect weather forecast: it is reported
separately and is never selectable.

Protocol: phase 'validation' fits on 2023-01..2024-09, scores 2024-10..12, selects and
writes a hash lock without reading any 2025 file. Phase 'test' verifies the lock, code
and input hashes, then opens 2025-01..06 once with no refit. All timestamps are local
Korean wall time, matching the panel.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import json
import os
from pathlib import Path
import pickle
import platform
import re
import shutil
import tempfile
import time

# Set before importing NumPy / sklearn. threadpool_limits also covers libraries
# already imported by callers of the public convenience interfaces.
for _name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
    os.environ[_name] = "2"

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_info, threadpool_limits


ROOT = Path(__file__).resolve().parents[2]
OBSERVED = "observed_departure_date"
PROTOCOL = "daily_00_next_24h_v2_calendar_weather_station_day_q"
TARGETS = ["departures", "returns"]
FEATURES = [f"{target}_lag_{lag}" for target in TARGETS for lag in [24, 168, 336]] + [
    "departures_mean_28", "returns_mean_28", "hour", "weekday", "month"]
KEYS = ["station_id", "event_time", "cutoff"]
PRED_COLUMNS = KEYS + ["model", "pred_departures", "pred_returns"]
MODEL_PARAMS = dict(loss="poisson", max_iter=100, max_leaf_nodes=15,
                    learning_rate=0.1, random_state=42, early_stopping=False)
SPLITS = {"train": ("2023-01-01", "2024-09-30"),
          "validation": ("2024-10-01", "2024-12-31"),
          "test": ("2025-01-01", "2025-06-30")}
EXCLUDED = ("2025-07-01", "2025-07-31")
ACTIVITY_SQL = "CASE WHEN prior_events_28 < 28 THEN 'low_under_1_event_daily' WHEN prior_events_28 < 280 THEN 'medium_1_to_10_events_daily' ELSE 'high_10plus_events_daily' END"
_SPILL_DIRECTORY = Path(tempfile.gettempdir()) / f"nubija-forecast-{os.getpid()}"

# Context features. Order matters: every model uses a prefix of ALL_HOURLY / ALL_DAILY.
CALENDAR_FEATURES = ["cal_holiday", "cal_offday", "cal_prev_offday", "cal_next_offday",
                     "cal_lag7_offday", "cal_lag14_offday", "cal_mean28_offdays", "cal_major_holiday"]
WEATHER_PAST = ["wx_prev_day_rain_mm", "wx_prev_day_temp_mean", "wx_prev_day_temp_max", "wx_prev_day_wind_mean"]
WEATHER_ORACLE_DAY = ["wx_day_rain_mm", "wx_day_temp_mean", "wx_day_temp_max", "wx_day_wind_mean"]
WEATHER_ORACLE_HOUR = ["wx_hour_rain_mm", "wx_hour_temp"]
CONTEXT_HOURLY = CALENDAR_FEATURES + WEATHER_PAST + WEATHER_ORACLE_DAY + WEATHER_ORACLE_HOUR
ALL_HOURLY = FEATURES + CONTEXT_HOURLY
# Station-day need q: hours 02~23 (rebalancing at 02:00), departures before returns
# inside an hour = simulate_rebalancing.q_from_hourly on run_rebalancing_experiments.PLAN_HOURS.
Q_HOURS = slice(2, 24)
DAILY_BASE = ["q_lag_1", "q_lag_7", "q_lag_14", "q_lag_21", "q_lag_28", "q_mean_4w", "q_std_4w", "q_rule4w",
              "dep_lag_1d", "dep_lag_7d", "dep_mean_4w", "ret_lag_1d", "ret_lag_7d", "ret_mean_4w",
              "q_station_mean", "station_age_capped", "events_28d", "weekday", "month"]
ALL_DAILY = DAILY_BASE + CALENDAR_FEATURES + WEATHER_PAST + WEATHER_ORACLE_DAY

# When each input is known relative to the D 00:00 cutoff. Only 'oracle' is after it.
AVAILABILITY = {f: "oracle_observed_after_cutoff" for f in WEATHER_ORACLE_DAY + WEATHER_ORACLE_HOUR}
AVAILABILITY.update({f: "published_calendar" for f in CALENDAR_FEATURES + ["hour", "weekday", "month"]})
for _f in FEATURES + DAILY_BASE + WEATHER_PAST:
    AVAILABILITY.setdefault(_f, "observed_before_cutoff")

HOURLY_MODELS = {"baseline": None,            # 4-week same weekday-hour mean
                 "baseline_lastweek": None,   # same hour one week earlier
                 "hist_gb_poisson": FEATURES,
                 "gb_calendar": FEATURES + CALENDAR_FEATURES,
                 "gb_calendar_weather": FEATURES + CALENDAR_FEATURES + WEATHER_PAST,
                 "gb_oracle_weather": ALL_HOURLY}
DAILY_MODELS = {"qgb_lags": DAILY_BASE,
                "qgb_calendar": DAILY_BASE + CALENDAR_FEATURES,
                "qgb_calendar_weather": DAILY_BASE + CALENDAR_FEATURES + WEATHER_PAST,
                "qgb_oracle_weather": ALL_DAILY}
ORACLE_MODELS = frozenset({"gb_oracle_weather", "qgb_oracle_weather"})
# q rules without learning: A = last week's q, B = mean of the last 4 same-weekday q,
# R = q of the 4-week mean hourly curve (= hourly 'baseline' curve, the simulator's rule4w).
Q_RULES = {"baseline_lastweek": "q_lag_7", "q_mean4w": "q_mean_4w", "baseline": "q_rule4w"}
HOURLY_SELECTION_ORDER = ["baseline", "baseline_lastweek", "hist_gb_poisson", "gb_calendar", "gb_calendar_weather"]
Q_AI_ORDER = ["qgb_lags", "qgb_calendar", "qgb_calendar_weather"]
HOURLY_RULE = ("lowest validation hourly departures_MAE + returns_MAE among non-oracle hourly models; "
               "earlier (simpler) candidate wins ties")
Q_AI_RULE = ("lowest validation MAE of raw q against hourly q (02~23h, departures first) over station-days "
             "with activity in the prior 28 days, among non-oracle direct GB models; earlier (simpler) wins ties")
LABELS = {"baseline": "기준선: 최근 4주 같은 요일 평균",
          "baseline_lastweek": "기준선A: 지난주 같은 요일",
          "q_mean4w": "기준선B: 최근 4주 같은 요일 q 평균",
          "hist_gb_poisson": "기존 GB(시간)",
          "gb_calendar": "GB+달력(시간)",
          "gb_calendar_weather": "GB+달력+날씨 누출 없음(시간)",
          "gb_oracle_weather": "GB+달력+당일 관측 날씨, 오라클(시간)",
          "qgb_lags": "q 직접 GB(시차)",
          "qgb_calendar": "q 직접 GB+달력",
          "qgb_calendar_weather": "q 직접 GB+달력+날씨 누출 없음",
          "qgb_oracle_weather": "q 직접 GB+달력+당일 관측 날씨, 오라클"}
Q_LABELS = {**LABELS, "baseline": "규칙R: 4주 평균 시간곡선의 q(시뮬레이터 rule4w)"}

# Public-office holidays missing from the KASI 2023~2025 TXT, which was generated before
# they were designated: 정부 공식 발표 기준 보완 (originals not stored locally; see
# data/metadata/forecast.md). The resulting list was checked against the parent's list.
HOLIDAY_SUPPLEMENT = {"2023-05-29": "대체공휴일(부처님오신날)", "2023-10-02": "임시공휴일",
                      "2024-10-01": "임시공휴일(국군의 날)", "2025-01-27": "임시공휴일(설 연휴)",
                      "2025-06-03": "제21대 대통령선거일"}
PRIOR_TEST_EXPOSURE = ("v1 run (completed 2026-10-17T01:53Z) already created and scored 2025-01..06 test "
                       "predictions for baseline and hist_gb_poisson. This v2 worker did not open v1 test "
                       "scores before the v2 lock; candidates and rules were fixed on validation only. The test "
                       "period is therefore opened a second time for this model family and is not pristine.")

if pd.Timestamp(SPLITS["train"][1]) >= pd.Timestamp(SPLITS["validation"][0]) or \
        pd.Timestamp(SPLITS["validation"][1]) >= pd.Timestamp(SPLITS["test"][0]) or \
        pd.Timestamp(SPLITS["test"][1]) >= pd.Timestamp(EXCLUDED[0]):
    raise AssertionError("splits must be ordered and disjoint, ending before July 2025")
for _features in list(HOURLY_MODELS.values()) + list(DAILY_MODELS.values()):
    if _features is not None and (ALL_HOURLY[:len(_features)] != _features and ALL_DAILY[:len(_features)] != _features):
        raise AssertionError("feature sets must be prefixes of the full matrix")


def _path(path: Path) -> str:
    return "'" + Path(path).resolve().as_posix().replace("'", "''") + "'"


def _paths(paths) -> str:
    return "[" + ",".join(_path(p) for p in paths) + "]"


def _connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='768MB'")
    con.execute(f"SET temp_directory={_path(_SPILL_DIRECTORY)}")
    return con


def _activity(events: float) -> str:
    return ("low_under_1_event_daily" if events < 28 else
            "medium_1_to_10_events_daily" if events < 280 else "high_10plus_events_daily")


def _months(start, end):
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    month = start.replace(day=1)
    while month <= end:
        following = month + pd.offsets.MonthBegin(1)
        yield max(month, start), min(following - pd.Timedelta(days=1), end)
        month = following


def make_features(panel: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Build the next 24 hours from strictly earlier observations.

    ``eligible_asof`` is the upstream past-only activity mask. A supplied
    ``history_complete_28`` is additionally respected; all 672 prior timestamps
    and both valid counts are independently required even without that column.
    Targets/weather are deliberately absent from the returned inputs.
    """
    cutoff = pd.Timestamp(cutoff)
    if cutoff != cutoff.normalize() or cutoff.tz is not None:
        raise ValueError("cutoff must be a naive local daily 00:00 timestamp")
    columns = KEYS + FEATURES + ["activity_stratum"]
    if pd.Timestamp("2025-07-01") <= cutoff < pd.Timestamp("2025-08-01"):
        return pd.DataFrame(columns=columns)
    data = panel.copy()
    data["event_time"] = pd.to_datetime(data.event_time)
    if data.duplicated(["station_id", "event_time"]).any():
        raise ValueError("Duplicate station-hour key")
    target = data[data.event_time.ge(cutoff) & data.event_time.lt(cutoff + pd.Timedelta(days=1))]
    history_times = pd.date_range(cutoff - pd.Timedelta(days=28), periods=672, freq="h")
    future_times = pd.date_range(cutoff, periods=24, freq="h")
    rows = []
    for station, future in target.groupby("station_id", sort=True):
        if len(future) != 24 or not future.eligible_asof.fillna(False).all():
            continue
        if "history_complete_28" in future and not future.history_complete_28.fillna(False).all():
            continue
        history = data[data.station_id.eq(station) & data.event_time.lt(cutoff)].set_index("event_time").reindex(history_times)
        values = history[TARGETS].to_numpy(dtype=float)
        if (not history.coverage_status.eq(OBSERVED).all() or not np.isfinite(values).all()
                or (values < 0).any()):
            continue
        activity = _activity(float(values.sum()))
        for t in future_times:
            row = dict(station_id=str(station), event_time=t, cutoff=cutoff,
                       hour=t.hour, weekday=t.dayofweek, month=t.month, activity_stratum=activity)
            for target_name in TARGETS:
                for lag in [24, 168, 336]:
                    row[f"{target_name}_lag_{lag}"] = float(history.loc[t - pd.Timedelta(hours=lag), target_name])
                row[f"{target_name}_mean_28"] = float(np.mean([
                    history.loc[t - pd.Timedelta(days=d), target_name] for d in [7, 14, 21, 28]]))
            rows.append(row)
    return pd.DataFrame(rows, columns=columns).sort_values(["station_id", "event_time"]).reset_index(drop=True)


def build_feature_parquet(panel_paths: list[Path], masks_path: Path, output: Path,
                          start: str, end: str) -> None:
    """Disk-backed equivalent of make_features, using a verified hourly grid."""
    start_day, end_day = pd.Timestamp(start), pd.Timestamp(end)
    first = start_day - pd.Timedelta(days=28)
    last = end_day + pd.Timedelta(days=1)
    paths = _paths(panel_paths)
    con = _connection()
    try:
        con.execute(f"""CREATE TEMP VIEW source_all AS SELECT * FROM read_parquet({paths})
            WHERE event_time >= TIMESTAMP '{first}' AND event_time < TIMESTAMP '{last}'""")
        # Positional lags are exact elapsed-hour lags only on this dense grid.
        invalid = con.execute("""SELECT count(*) FROM (SELECT station_id, count(*) n,
            count(DISTINCT event_time) distinct_n, date_diff('hour',min(event_time),max(event_time))+1 expected
            FROM source_all GROUP BY station_id HAVING n != expected OR n != distinct_n)""").fetchone()[0]
        if invalid:
            raise ValueError("Panel must have one contiguous row per station-hour")
        lag_columns = []
        for target in TARGETS:
            for lag in [24, 168, 336, 504, 672]:
                lag_columns.append(f"lag({target},{lag}) OVER w AS {target}_lag_{lag}")
        means = [f"({t}_lag_168 + {t}_lag_336 + {t}_lag_504 + {t}_lag_672)/4.0 AS {t}_mean_28" for t in TARGETS]
        query = f"""COPY (
            WITH clean AS (SELECT station_id,event_time,eligible_asof,coverage_status,
                CASE WHEN coverage_status='{OBSERVED}' THEN departures END AS departures,
                CASE WHEN coverage_status='{OBSERVED}' THEN returns END AS returns FROM source),
            lagged AS (SELECT *, {','.join(lag_columns)},
                count(departures) OVER h AS n_dep, count(returns) OVER h AS n_ret,
                min(least(departures,returns)) OVER h AS history_min,
                sum(departures+returns) OVER h AS prior_events_28
                FROM clean WINDOW w AS (PARTITION BY station_id ORDER BY event_time),
                h AS (PARTITION BY station_id ORDER BY event_time ROWS BETWEEN 672 PRECEDING AND 1 PRECEDING)),
            daily_history AS (SELECT station_id,event_time AS cutoff,n_dep,n_ret,history_min,prior_events_28
                FROM lagged WHERE event_time=date_trunc('day',event_time)),
            prepared AS (SELECT *, {','.join(means)}, date_trunc('day',event_time) cutoff FROM lagged)
            SELECT p.station_id,p.event_time,p.cutoff,
                {','.join('p.'+f for f in FEATURES[:8])},
                hour(p.event_time) AS hour, isodow(p.event_time)-1 AS weekday,month(p.event_time) AS month,
                {ACTIVITY_SQL.replace('prior_events_28', 'h.prior_events_28')} AS activity_stratum, p.departures,p.returns,m.history_stratum
            FROM prepared p JOIN daily_history h USING(station_id,cutoff) JOIN read_parquet({_path(masks_path)}) m
                ON p.station_id=m.station_id AND p.cutoff=m.target_date
            WHERE p.event_time >= TIMESTAMP '{start_day}' AND p.event_time < TIMESTAMP '{last}'
                AND NOT (p.event_time >= TIMESTAMP '2025-07-01' AND p.event_time < TIMESTAMP '2025-08-01')
                AND p.coverage_status='{OBSERVED}' AND p.eligible_asof AND m.eligible_asof
                AND m.history_complete_28 AND m.forecast_cutoff=p.cutoff
                AND h.n_dep=672 AND h.n_ret=672 AND h.history_min>=0
            ORDER BY p.event_time,p.station_id
        ) TO __FEATURE_OUTPUT__ (FORMAT PARQUET, COMPRESSION ZSTD)"""
        # Station windows are independent. Partitioning computation keeps the
        # window/hash-join materialization below the same 768MB limit, retaining
        # every row and precisely the same daily-cutoff features.
        stations = con.execute("SELECT DISTINCT station_id FROM source_all ORDER BY station_id").fetchdf().station_id.tolist()
        writer = None
        try:
            with tempfile.TemporaryDirectory(prefix="feature-parts-", dir=output.parent) as tmp:
                part = Path(tmp) / "part.parquet"
                for offset in range(0, len(stations), 32):
                    ids = ",".join("'" + str(s).replace("'", "''") + "'" for s in stations[offset:offset+32])
                    con.execute(f"CREATE OR REPLACE TEMP VIEW source AS SELECT * FROM source_all WHERE station_id IN ({ids})")
                    con.execute(query.replace("__FEATURE_OUTPUT__", _path(part)))
                    with pq.ParquetFile(part) as parquet:
                        if writer is None:
                            writer = pq.ParquetWriter(output, parquet.schema_arrow, compression="zstd")
                        for batch in parquet.iter_batches(batch_size=100000):
                            writer.write_batch(batch)
                    part.unlink()
        finally:
            if writer is not None:
                writer.close()
    finally:
        con.close()


# ---------------------------------------------------------------- calendar & weather

def kasi_holidays(paths) -> pd.Series:
    """Public-office holidays from KASI '국경일과 공휴일' tables, plus the supplement.

    Rows marked '**' (national days that are not holidays, e.g. 제헌절) are excluded.
    Returns names indexed by date; attrs['covered_years'] lists the parsed years.
    """
    holidays, years = {}, set()
    for path in paths:
        text = Path(path).read_text(encoding="utf-8")
        year = int(re.search(r"(20\d{2})년", text).group(1))
        table = text.split("국경일과 공휴일", 1)[1].split("\n=", 1)[0]
        found = 0
        for line in table.splitlines():
            match = re.match(r"\s*(\S.*?)\s{2,}(\d+)월\s*(\d+)일(?:~\s*(\d+)월\s*(\d+)일)?", line)
            if not match:
                continue
            name = re.sub(r"\s+", "", match.group(1))  # '추  석' -> '추석'
            if name.endswith("**"):
                continue
            first = pd.Timestamp(year, int(match.group(2)), int(match.group(3)))
            last = pd.Timestamp(year, int(match.group(4)), int(match.group(5))) if match.group(4) else first
            for day in pd.date_range(first, last):
                holidays[day] = holidays[day] + "·" + name.rstrip("*") if day in holidays else name.rstrip("*")
            found += 1
        if not found:
            raise ValueError(f"No holiday rows parsed from {path}")
        years.add(year)
    for day, name in HOLIDAY_SUPPLEMENT.items():
        day = pd.Timestamp(day)
        if day.year in years:
            holidays[day] = holidays[day] + "·" + name if day in holidays else name
    result = pd.Series(holidays, dtype=object).sort_index()
    result.attrs["covered_years"] = sorted(years)
    return result


def calendar_table(holidays: pd.Series) -> pd.DataFrame:
    """Day calendar over the covered years; lag columns are NaN where history is absent."""
    years = holidays.attrs["covered_years"]
    if years != list(range(years[0], years[-1] + 1)):
        raise ValueError("calendar years must be contiguous")
    days = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31")
    names = holidays.reindex(days)
    holiday = names.notna()
    off = holiday | (days.dayofweek >= 5)
    major = names.fillna("").str.contains("설|추석")
    run = (off != off.shift()).cumsum()
    inside = (off & run.isin(run[major].unique())).to_numpy()
    code = np.where(inside, 1, 0)
    for k in (1, 2):
        before = np.r_[inside[k:], [False] * k] & ~inside
        after = np.r_[[False] * k, inside[:-k]] & ~inside
        code = np.where((code == 0) & before, 2, code)
        code = np.where((code == 0) & after, 3, code)
    offf = off.astype(float)
    table = pd.DataFrame({"holiday_name": names, "cal_holiday": holiday.astype(float), "cal_offday": offf,
                          "cal_prev_offday": offf.shift(1), "cal_next_offday": offf.shift(-1),
                          "cal_lag7_offday": offf.shift(7), "cal_lag14_offday": offf.shift(14),
                          "cal_mean28_offdays": sum(offf.shift(k) for k in [7, 14, 21, 28]),
                          "cal_major_holiday": code.astype(float)}, index=days)
    table.index.name = "target_date"
    return table


def weather_tables(hourly_csv: Path, daily_csvs) -> tuple[pd.DataFrame, pd.DataFrame]:
    """ASOS 155 hourly rain/temperature and daily totals, missing kept as NaN.

    Hourly rn: a blank stays missing (NaN), never 0. ASOS reports precipitation every
    3 hours in Nov~Mar and the blank meaning is unconfirmed; rnQcflg 9 is missing as well.
    Daily sumRn blank is a no-rain day -> 0: of 685 blank days only 2023-11-29 has a
    rain record in iscs (trace, sumRnDur 0), while all 411 non-blank days have one.
    Daily rain features therefore come from sumRn only. Other gaps (one maxTa) stay NaN.
    """
    hourly = pd.read_csv(hourly_csv, encoding="utf-8-sig", usecols=["tm", "ta", "rn", "rnQcflg"])
    hourly["tm"] = pd.to_datetime(hourly.tm, format="%Y-%m-%d %H:%M")
    if hourly.tm.duplicated().any():
        raise ValueError("duplicate ASOS hourly time")
    rain = hourly.rn.astype(float).where(pd.to_numeric(hourly.rnQcflg, errors="coerce").ne(9))
    hourly_wx = pd.DataFrame({"rain_mm": rain.to_numpy(), "temp": hourly.ta.astype(float).to_numpy()},
                             index=pd.DatetimeIndex(hourly.tm))
    daily = pd.concat([pd.read_csv(p, encoding="utf-8-sig", usecols=["tm", "sumRn", "avgTa", "maxTa", "avgWs"])
                       for p in daily_csvs])
    daily["tm"] = pd.to_datetime(daily.tm, format="%Y-%m-%d")
    if daily.tm.duplicated().any():
        raise ValueError("duplicate ASOS daily date")
    daily_wx = pd.DataFrame({"day_rain_mm": daily.sumRn.astype(float).fillna(0.0).to_numpy(),
                             "day_temp_mean": daily.avgTa.astype(float).to_numpy(),
                             "day_temp_max": daily.maxTa.astype(float).to_numpy(),
                             "day_wind_mean": daily.avgWs.astype(float).to_numpy()},
                            index=pd.DatetimeIndex(daily.tm))
    return hourly_wx.sort_index(), daily_wx.sort_index()


def context_tables(holidays: pd.Series, hourly_wx: pd.DataFrame, daily_wx: pd.DataFrame,
                   start, end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Context for target days [start, end] forecast at D 00:00.

    cal_* come from the published calendar; wx_prev_* are the daily observations of
    day D-1, complete at the cutoff. wx_day_* and wx_hour_* are observed on D itself:
    ORACLE inputs. Returns (daily, hourly) tables.
    """
    days = pd.date_range(start, end)
    calendar = calendar_table(holidays)
    if not days.isin(calendar.index).all():
        raise ValueError("calendar does not cover every target day")
    daily = calendar.reindex(days).copy()
    previous = days - pd.Timedelta(days=1)
    for name, column in [("rain_mm", "day_rain_mm"), ("temp_mean", "day_temp_mean"),
                         ("temp_max", "day_temp_max"), ("wind_mean", "day_wind_mean")]:
        daily[f"wx_prev_day_{name}"] = daily_wx[column].reindex(previous).to_numpy()
        daily[f"wx_day_{name}"] = daily_wx[column].reindex(days).to_numpy()   # ORACLE
    daily["day_type"] = np.where(daily.cal_holiday.eq(1), "holiday",
                                 np.where(days.dayofweek >= 5, "weekend", "weekday"))
    daily["rain_day"] = np.where(daily.wx_day_rain_mm.isna(), "unknown",
                                 np.where(daily.wx_day_rain_mm >= 1.0, "rain_1mm_plus", "dry_under_1mm"))
    daily["major_holiday_window"] = daily.cal_major_holiday.map(
        {0: "none", 1: "seollal_chuseok_block", 2: "1_2_days_before", 3: "1_2_days_after"})
    daily.index.name = "target_date"
    hours = pd.date_range(days[0], days[-1] + pd.Timedelta(hours=23), freq="h")
    day_columns = CALENDAR_FEATURES + WEATHER_PAST + WEATHER_ORACLE_DAY
    hourly = pd.DataFrame(daily[day_columns].reindex(hours.normalize()).to_numpy(), index=hours, columns=day_columns)
    # Rain at tm=t+1h accumulates over [t, t+1h): the same hour as the event bucket.
    hourly["wx_hour_rain_mm"] = hourly_wx.rain_mm.reindex(hours + pd.Timedelta(hours=1)).to_numpy()
    hourly["wx_hour_temp"] = hourly_wx.temp.reindex(hours + pd.Timedelta(hours=1)).to_numpy()
    return daily, hourly[CONTEXT_HOURLY]


def _context_index(times, index: pd.DatetimeIndex) -> np.ndarray:
    idx = index.get_indexer(pd.DatetimeIndex(times).as_unit("ns"))
    if (idx < 0).any():
        raise ValueError("calendar/weather context missing for event hours")
    return idx


def add_context(frame: pd.DataFrame, hourly_ctx: pd.DataFrame) -> pd.DataFrame:
    values = hourly_ctx.to_numpy(dtype=np.float64)[_context_index(frame.event_time.to_numpy(), hourly_ctx.index)]
    return frame.assign(**{column: values[:, j] for j, column in enumerate(hourly_ctx.columns)})


# ---------------------------------------------------------------- exact q and curves

def curve_q(departures, returns) -> np.ndarray:
    """Row-wise q = max_k(sum_{h<=k} dep_h - sum_{h<k} ret_h), at least 0.

    Same arithmetic as simulate_rebalancing.q_from_hourly (departures before returns
    inside an hour); pass hourly columns Q_HOURS for the station-day need q.
    """
    d, r = np.asarray(departures, dtype=float), np.asarray(returns, dtype=float)
    cum_ret_prev = np.concatenate([np.zeros((d.shape[0], 1)), np.cumsum(r, axis=1)[:, :-1]], axis=1)
    return np.maximum((np.cumsum(d, axis=1) - cum_ret_prev).max(axis=1), 0.0)


def observed_daily_q(event_paths, masks_path: Path, start, end) -> pd.DataFrame:
    """Exact-timestamp q (support_policy_evaluation.md) for every observed station-day.

    Main-cohort events; departures first within a timestamp; an observed day without
    events is 0. Not limited to eligible days so past days can serve as lags.
    """
    paths = _paths(event_paths)
    con = _connection()
    frames = []
    try:
        for first, last in _months(start, end):
            frames.append(con.execute(f"""
                WITH cand AS (SELECT CAST(station_id AS VARCHAR) station_id, CAST(target_date AS DATE) target_date
                    FROM read_parquet({_path(masks_path)}) WHERE coverage_status='{OBSERVED}'
                    AND CAST(target_date AS DATE) BETWEEN DATE '{first.date()}' AND DATE '{last.date()}'),
                ev AS (SELECT CAST(station_id AS VARCHAR) station_id, CAST(event_time AS DATE) target_date, event_time,
                    SUM(main_departures) d, SUM(main_returns) r FROM read_parquet({paths})
                    WHERE coverage_status='{OBSERVED}' AND event_time >= TIMESTAMP '{first.date()}'
                    AND event_time < TIMESTAMP '{(last + pd.Timedelta(days=1)).date()}' GROUP BY 1,2,3),
                peaks AS (SELECT station_id, target_date, d, r, SUM(d-r) OVER (PARTITION BY station_id,target_date
                    ORDER BY event_time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) + r AS peak FROM ev)
                SELECT c.station_id, CAST(c.target_date AS TIMESTAMP) target_date,
                    CAST(GREATEST(0, COALESCE(MAX(p.peak), 0)) AS BIGINT) q,
                    CAST(COALESCE(SUM(p.d), 0) AS BIGINT) main_departures,
                    CAST(COALESCE(SUM(p.r), 0) AS BIGINT) main_returns
                FROM cand c LEFT JOIN peaks p USING (station_id, target_date) GROUP BY 1, 2""").fetchdf())
    finally:
        con.close()
    out = pd.concat(frames, ignore_index=True)
    out["target_date"] = pd.to_datetime(out.target_date).astype("datetime64[ns]")
    if out.duplicated(["station_id", "target_date"]).any():
        raise ValueError("duplicate station-day q")
    return out.sort_values(["target_date", "station_id"]).reset_index(drop=True)


def _per_day(con, sql: str, numeric: list[str]) -> tuple[pd.DataFrame, dict]:
    """Rows ordered by station_id,cutoff,event_time -> (keys, (days,24) arrays)."""
    data = con.execute(sql).fetchnumpy()
    n = len(data["station_id"])
    if n % 24:
        raise ValueError("every station-day needs exactly 24 hours")
    station = np.asarray(data["station_id"]).reshape(-1, 24)
    cutoff = np.asarray(data["cutoff"]).astype("datetime64[ns]").reshape(-1, 24)
    times = np.asarray(data["event_time"]).astype("datetime64[ns]").reshape(-1, 24)
    expected = cutoff[:, :1] + np.arange(24) * np.timedelta64(1, "h")
    if not ((station == station[:, :1]).all() and (cutoff == cutoff[:, :1]).all() and (times == expected).all()):
        raise ValueError("station-day must contain hours 00..23 at its own cutoff")
    keys = pd.DataFrame({"station_id": station[:, 0].astype(str), "target_date": pd.to_datetime(cutoff[:, 0])})
    return keys, {c: np.asarray(data[c], dtype=float).reshape(-1, 24) for c in numeric}


def hourly_cube(panel_paths, start, end) -> dict:
    """Dense station x day x hour counts of the hourly panel on observed dates.

    Zero means no event on an observed date; observed is False for unobserved dates.
    """
    days = pd.date_range(start, end)
    source = f"read_parquet({_paths(panel_paths)})"
    where = (f"coverage_status='{OBSERVED}' AND event_time >= TIMESTAMP '{days[0]}' "
             f"AND event_time < TIMESTAMP '{days[-1] + pd.Timedelta(days=1)}'")
    con = _connection()
    try:
        stations = pd.Index(sorted(con.execute(f"SELECT DISTINCT CAST(station_id AS VARCHAR) s FROM {source}").fetchdf().s))
        con.register("station_index", pd.DataFrame({"sid": stations.to_numpy(), "sidx": np.arange(len(stations), dtype=np.int32)}))
        n, nulls, top = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE departures IS NULL OR returns IS NULL),
            max(greatest(departures, returns)) FROM {source} WHERE {where}""").fetchone()
        if nulls or (top or 0) > np.iinfo(np.int16).max:
            raise ValueError("observed hourly counts must be present and fit int16")
        dep = np.zeros((len(stations), len(days), 24), dtype=np.int16)
        ret = np.zeros_like(dep)
        hours = np.zeros((len(stations), len(days)), dtype=np.int16)
        reader = con.execute(f"""SELECT i.sidx, date_diff('day', DATE '{days[0].date()}', CAST(p.event_time AS DATE)) didx,
            hour(p.event_time) h, p.departures, p.returns FROM {source} p
            JOIN station_index i ON CAST(p.station_id AS VARCHAR) = i.sid WHERE {where}""").to_arrow_reader(batch_size=1_000_000)
        for batch in reader:
            s, d, h = (batch.column(c).to_numpy(zero_copy_only=False) for c in ["sidx", "didx", "h"])
            dep[s, d, h] = batch.column("departures").to_numpy(zero_copy_only=False)
            ret[s, d, h] = batch.column("returns").to_numpy(zero_copy_only=False)
            np.add.at(hours, (s, d), 1)
    finally:
        con.close()
    if int(hours.sum()) != n or ((hours > 0) & (hours != 24)).any():
        raise ValueError("every observed station-day needs exactly 24 distinct hours")
    return {"stations": stations, "days": days, "dep": dep, "ret": ret, "observed": hours == 24}


def daily_table(cube: dict, masks_path: Path, daily_ctx: pd.DataFrame, start, end, strict: bool = True) -> pd.DataFrame:
    """Station-days with activity in the prior 28 days (masks.observed_activity_prior_28d).

    q_actual uses hours 02~23 of D (curve_q). Every input is computed from days
    before D or from the calendar/weather context; strict=True refuses rows whose
    28-day history is not fully observed instead of dropping them.
    """
    stations, days, dep, ret, observed = (cube[k] for k in ["stations", "days", "dep", "ret", "observed"])
    n_stations, n_days = observed.shape
    q = curve_q(dep[:, :, Q_HOURS].reshape(n_stations * n_days, -1),
                ret[:, :, Q_HOURS].reshape(n_stations * n_days, -1)).reshape(n_stations, n_days)
    dep_day, ret_day = dep.sum(axis=2, dtype=np.float64), ret.sum(axis=2, dtype=np.float64)
    for array in (q, dep_day, ret_day):
        array[~observed] = np.nan
    events = np.nan_to_num(dep_day + ret_day)
    zeros = np.zeros((n_stations, 1))
    cum_events = np.concatenate([zeros, np.cumsum(events, axis=1)], axis=1)
    cum_observed = np.concatenate([zeros, np.cumsum(observed, axis=1)], axis=1)
    active = events > 0
    first = np.where(active.any(axis=1), active.argmax(axis=1), n_days)
    since_first = (np.arange(n_days)[None, :] >= first[:, None]) & observed
    cum_q = np.concatenate([zeros, np.cumsum(np.where(since_first, q, 0.0), axis=1)], axis=1)
    cum_n = np.concatenate([zeros, np.cumsum(since_first, axis=1)], axis=1)
    con = _connection()
    try:
        table = con.execute(f"""SELECT CAST(station_id AS VARCHAR) station_id, CAST(target_date AS TIMESTAMP) target_date,
            eligible_asof AND history_complete_28 AS in_hourly_universe, history_stratum
            FROM read_parquet({_path(masks_path)}) WHERE coverage_status='{OBSERVED}' AND observed_activity_prior_28d
            AND target_date BETWEEN TIMESTAMP '{pd.Timestamp(start)}' AND TIMESTAMP '{pd.Timestamp(end)}'
            ORDER BY target_date, station_id""").fetchdf()
    finally:
        con.close()
    table["target_date"] = pd.to_datetime(table.target_date).astype("datetime64[ns]")
    s = stations.get_indexer(table.station_id)
    d = (table.target_date - days[0]).dt.days.to_numpy()
    ok = (s >= 0) & (d >= 28) & (d < n_days)
    ok[ok] = cum_observed[s[ok], d[ok] + 1] - cum_observed[s[ok], d[ok] - 28] == 29
    if strict and not ok.all():
        raise ValueError(f"{int((~ok).sum())} station-days lack a fully observed 28-day history")
    table, s, d = table[ok].reset_index(drop=True), s[ok], d[ok]
    table["q_actual"] = q[s, d]
    table["departures_day"], table["returns_day"] = dep_day[s, d], ret_day[s, d]
    table["netflow_day"] = table.departures_day - table.returns_day
    for k in [1, 7, 14, 21, 28]:
        table[f"q_lag_{k}"] = q[s, d - k]
    weeks = [7, 14, 21, 28]
    past_q = np.column_stack([q[s, d - k] for k in weeks])
    table["q_mean_4w"], table["q_std_4w"] = past_q.mean(axis=1), past_q.std(axis=1, ddof=1)
    mean_dep = sum(dep[s, d - k].astype(np.float64) for k in weeks) / 4.0
    mean_ret = sum(ret[s, d - k].astype(np.float64) for k in weeks) / 4.0
    table["q_rule4w"] = curve_q(mean_dep[:, Q_HOURS], mean_ret[:, Q_HOURS])
    for short, values in [("dep", dep_day), ("ret", ret_day)]:
        table[f"{short}_lag_1d"], table[f"{short}_lag_7d"] = values[s, d - 1], values[s, d - 7]
        table[f"{short}_mean_4w"] = np.mean([values[s, d - k] for k in weeks], axis=0)
    table["events_28d"] = cum_events[s, d] - cum_events[s, d - 28]
    table["q_station_mean"] = cum_q[s, d] / np.where(cum_n[s, d] > 0, cum_n[s, d], np.nan)
    age = d - first[s]
    table["station_age_capped"] = np.minimum(age, 28)
    table["station_age_group"] = np.where(age < 28, "new_under_28d", "established")
    table["activity_stratum"] = np.select([table.events_28d < 28, table.events_28d < 280],
                                          ["low_under_1_event_daily", "medium_1_to_10_events_daily"], "high_10plus_events_daily")
    table["weekday"], table["month"] = table.target_date.dt.dayofweek, table.target_date.dt.month
    context = daily_ctx.reindex(table.target_date)
    for column in CALENDAR_FEATURES + WEATHER_PAST + WEATHER_ORACLE_DAY + ["day_type", "rain_day", "major_holiday_window"]:
        table[column] = context[column].to_numpy()
    required = DAILY_BASE + CALENDAR_FEATURES + ["q_actual", "departures_day", "returns_day"]
    if table[required].isna().any().any() or (table.events_28d <= 0).any():
        raise ValueError("station-day inputs incomplete or inactive in the prior 28 days")
    table["rule4w_band"] = pd.cut(table.q_rule4w, [-np.inf, 1, 3, 6, 10, np.inf], right=False,
                                  labels=["0_1", "1_3", "3_6", "6_10", "10_plus"]).astype(str)
    return table


def _daily_from_predictions(pred_path: Path, start, end, model: str) -> pd.DataFrame:
    con = _connection()
    parts = []
    try:
        for first, last in _months(start, end):
            keys, arr = _per_day(con, f"""SELECT station_id, cutoff, event_time, pred_departures, pred_returns
                FROM read_parquet({_path(pred_path)}) WHERE model='{model}'
                AND cutoff BETWEEN TIMESTAMP '{first}' AND TIMESTAMP '{last}'
                ORDER BY station_id, cutoff, event_time""", ["pred_departures", "pred_returns"])
            keys["pred_departures_day"] = arr["pred_departures"].sum(axis=1)
            keys["pred_returns_day"] = arr["pred_returns"].sum(axis=1)
            keys["q_curve_raw"] = curve_q(arr["pred_departures"][:, Q_HOURS], arr["pred_returns"][:, Q_HOURS])
            parts.append(keys)
    finally:
        con.close()
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- models

def _check_matrix(matrix: np.ndarray, features: list[str]) -> np.ndarray:
    """Non-weather inputs finite and nonnegative; weather may be missing (NaN), never inf."""
    for j, feature in enumerate(features):
        column = matrix[:, j]
        if feature.startswith("wx_"):
            if np.isinf(column).any():
                raise ValueError("Weather features may be missing, never infinite")
        elif not np.isfinite(column).all() or (column < 0).any():
            raise ValueError("Model features must be finite and nonnegative")
        column[column == 0] = 0.0  # canonical positive zero
    return matrix


def _matrix(frame: pd.DataFrame, features: list[str] = FEATURES) -> np.ndarray:
    return _check_matrix(frame[features].to_numpy(dtype=np.float64), features)


def _fit_targets(matrix: np.ndarray, targets: dict) -> dict:
    fitted = {}
    with threadpool_limits(limits=2):
        for name, raw in targets.items():
            values = np.array(raw, dtype=np.float64)
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError("Poisson targets must be finite and nonnegative")
            values[values == 0] = 0.0
            if not values.any():
                fitted[name] = 0.0
            else:
                model = HistGradientBoostingRegressor(**MODEL_PARAMS)
                model.fit(matrix, values)
                fitted[name] = model
    return fitted


def _predict(future: pd.DataFrame, model_name: str, fitted: dict | None = None) -> pd.DataFrame:
    result = future[KEYS].copy()
    result["model"] = model_name
    features = HOURLY_MODELS[model_name]
    matrix = _matrix(future, features) if features else None
    with threadpool_limits(limits=2):
        for target in TARGETS:
            if model_name == "baseline":
                values = future[f"{target}_mean_28"].to_numpy(dtype=float)
            elif model_name == "baseline_lastweek":
                values = future[f"{target}_lag_168"].to_numpy(dtype=float)
            else:
                model = fitted[model_name][target]
                values = np.full(len(future), model) if isinstance(model, float) else model.predict(matrix)
            if not np.isfinite(values).all():
                raise ValueError("Nonfinite prediction")
            result[f"pred_{target}"] = np.maximum(values, 0.0)
    return result[PRED_COLUMNS]


def fit_predict(train: pd.DataFrame, future: pd.DataFrame, model_name: str) -> pd.DataFrame:
    """Fit pooled count models for one hourly model name, or use a seasonal baseline."""
    if model_name not in HOURLY_MODELS:
        raise ValueError(f"Unknown model: {model_name}")
    features = HOURLY_MODELS[model_name]
    fitted = {model_name: _fit_targets(_matrix(train, features), {t: train[t] for t in TARGETS})} if features else None
    return _predict(future, model_name, fitted)


def flow_metrics(frame: pd.DataFrame) -> dict:
    result = {}
    for name in ["departures", "returns", "netflow"]:
        actual = (frame.departures - frame.returns if name == "netflow" else frame[name]).to_numpy(dtype=float)
        pred = (frame.pred_departures - frame.pred_returns if name == "netflow" else frame[f"pred_{name}"]).to_numpy(dtype=float)
        error = np.abs(actual - pred)
        denominator = float(np.abs(actual).sum())
        result[f"{name}_mae"] = float(error.mean()) if len(error) else np.nan
        result[f"{name}_wape"] = float(error.sum() / denominator) if denominator else np.nan
    return result


def select_model(scores: dict, order: list[str] = HOURLY_SELECTION_ORDER) -> str:
    """Predeclared: lowest validation score; the earlier (simpler) candidate wins ties.

    Oracle models use weather observed after the cutoff and are never selectable.
    """
    if set(scores) & ORACLE_MODELS:
        raise ValueError("oracle models cannot be selected")
    if not set(scores) <= set(order):
        raise ValueError("unknown candidate")
    candidates = [m for m in order if m in scores]
    if len(candidates) < 2 or not all(np.isfinite(scores[m]) for m in candidates):
        raise ValueError("Both validation scores must be finite")
    best = candidates[0]
    for model in candidates[1:]:
        if scores[model] < scores[best]:
            best = model
    return best


def district_reference(workbook: Path) -> pd.DataFrame:
    """Year-specific administrative labels for error reporting only."""
    frames = []
    with pd.ExcelFile(workbook) as excel:
        for sheet in excel.sheet_names:
            match = re.fullmatch(r"(20\d{2})년", sheet)
            if match:
                frame = pd.read_excel(excel, sheet_name=sheet, dtype=str)[["터미널번호", "구"]]
                frame = frame.rename(columns={"터미널번호": "station_id", "구": "district"})
                frame["station_id"] = frame.station_id.str.strip()
                frame["year"] = int(match.group(1))
                if frame.station_id.duplicated().any():
                    raise ValueError("Duplicate station in annual district reference")
                frames.append(frame)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- metrics

def _score_parquet(predictions: Path, actuals: Path, split: str) -> pd.DataFrame:
    con = _connection()
    try:
        con.execute(f"""CREATE TEMP VIEW scored AS SELECT p.*,a.departures,a.returns,a.district,a.activity_stratum,
            a.day_type,a.rain_day,cast(hour(p.event_time) AS VARCHAR) AS hour_group
            FROM read_parquet({_path(predictions)}) p JOIN read_parquet({_path(actuals)}) a
            USING(station_id,event_time,cutoff)""")
        expressions = []
        for name, actual, pred in [
            ("departures", "departures", "pred_departures"),
            ("returns", "returns", "pred_returns"),
            ("netflow", "departures-returns", "pred_departures-pred_returns")]:
            expressions += [f"avg(abs(({actual})-({pred}))) AS {name}_mae",
                            f"sum(abs(({actual})-({pred})))/nullif(sum(abs({actual})),0) AS {name}_wape",
                            f"sum(abs({actual})) AS {name}_absolute_actual_sum"]
        frames = []
        for dimension, column in [("overall", "'all'"), ("district", "district"), ("hour", "hour_group"),
                                  ("activity", "activity_stratum"), ("day_type", "day_type"), ("rain_day", "rain_day")]:
            group = con.execute(f"SELECT model,{column} AS group_value,count(*) n_hours,{','.join(expressions)} FROM scored GROUP BY ALL").fetchdf()
            group.insert(0, "dimension", dimension)
            group.insert(0, "split", split)
            frames.append(group)
        return pd.concat(frames, ignore_index=True).sort_values(["split", "dimension", "group_value", "model"]).reset_index(drop=True)
    finally:
        con.close()


E_DIMENSIONS = ["overall", "district", "activity_stratum", "day_type", "rain_day", "major_holiday_window", "month"]
U_DIMENSIONS = E_DIMENSIONS + ["station_age_group", "rule4w_band"]
LABEL_COLUMNS = ["q_actual", "q_exact", "departures_day", "returns_day", "netflow_day", "district", "activity_stratum",
                 "day_type", "rain_day", "major_holiday_window", "station_age_group", "rule4w_band"]


def forecast_metrics(frame: pd.DataFrame, split: str, dimensions: list[str]) -> pd.DataFrame:
    """Station-day errors by model and stratum.

    q: raw forecasts against q_actual (hours 02~23): MAE, bias, under-forecast rate and
    units, share within 2 bikes, WAPE, and qx_mae against exact-timestamp q. Rentals
    (hourly models only): MAE/WAPE and the share whose round-half-up forecast is within
    2 of the actual daily count.
    """
    d = frame.copy()
    d["q_abs"] = (d.q_raw - d.q_actual).abs()
    d["q_err"] = d.q_raw - d.q_actual
    d["q_under"] = (d.q_raw < d.q_actual).astype(float)
    d["q_under_units"] = (d.q_actual - d.q_raw).clip(lower=0)
    d["q_hit2"] = (d.q_abs <= 2).astype(float)
    d["qx_abs"] = (d.q_raw - d.q_exact).abs()
    for name in ["departures", "returns", "netflow"]:
        if f"pred_{name}_day" not in d:
            d[f"pred_{name}_day"] = np.nan
        d[f"{name}_abs"] = (d[f"pred_{name}_day"] - d[f"{name}_day"]).abs()
        d[f"{name}_actual_abs"] = d[f"{name}_day"].abs()
    d["departures_hit2"] = ((np.floor(d.pred_departures_day + 0.5) - d.departures_day).abs() <= 2).astype(float)
    d.loc[d.pred_departures_day.isna(), "departures_hit2"] = np.nan
    d["overall"] = "all"
    d["month"] = d.target_date.dt.month.astype(str)
    frames = []
    for dimension in dimensions:
        g = d.groupby(["model", dimension], sort=True).agg(
            n_station_days=("q_actual", "size"), q_mae=("q_abs", "mean"), q_bias=("q_err", "mean"),
            q_under_rate=("q_under", "mean"), q_under_units=("q_under_units", "mean"), q_within2=("q_hit2", "mean"),
            q_actual_mean=("q_actual", "mean"), q_pred_mean=("q_raw", "mean"), qx_mae=("qx_abs", "mean"),
            departures_day_mae=("departures_abs", "mean"), departures_actual_mean=("departures_actual_abs", "mean"),
            departures_day_within2=("departures_hit2", "mean"), returns_day_mae=("returns_abs", "mean"),
            returns_actual_mean=("returns_actual_abs", "mean"), netflow_day_mae=("netflow_abs", "mean"),
            netflow_actual_mean=("netflow_actual_abs", "mean")).reset_index()
        g["q_wape"] = g.q_mae / g.q_actual_mean.replace(0, np.nan)
        for name in ["departures", "returns", "netflow"]:
            g[f"{name}_day_wape"] = g[f"{name}_day_mae"] / g[f"{name}_actual_mean"].replace(0, np.nan)
        g = g.rename(columns={dimension: "group_value"})
        g.insert(0, "dimension", dimension)
        g.insert(0, "split", split)
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def city_metrics(frame: pd.DataFrame, split: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """City-wide daily totals over the station-days of ``frame``: percentage errors per day."""
    city = frame.groupby(["model", "target_date"], sort=True).agg(
        pred_departures=("pred_departures_day", lambda s: s.sum(min_count=1)),
        actual_departures=("departures_day", "sum"), pred_q=("q_raw", "sum"), actual_q=("q_actual", "sum"),
        day_type=("day_type", "first"), rain_day=("rain_day", "first")).reset_index()
    city["departures_pct_error"] = (city.pred_departures - city.actual_departures) / city.actual_departures * 100
    city["q_pct_error"] = (city.pred_q - city.actual_q) / city.actual_q.replace(0, np.nan) * 100
    city.insert(0, "split", split)
    frames = []
    city["overall"] = "all"
    for dimension in ["overall", "day_type", "rain_day"]:
        g = city.groupby(["model", dimension], sort=True).agg(
            n_days=("target_date", "size"),
            city_departures_mape=("departures_pct_error", lambda s: s.abs().mean()),
            city_departures_bias_pct=("departures_pct_error", "mean"),
            city_departures_max_ape=("departures_pct_error", lambda s: s.abs().max()),
            city_q_mape=("q_pct_error", lambda s: s.abs().mean()),
            city_q_bias_pct=("q_pct_error", "mean")).reset_index().rename(columns={dimension: "group_value"})
        g.insert(0, "dimension", dimension)
        g.insert(0, "split", split)
        frames.append(g)
    return city.drop(columns="overall"), pd.concat(frames, ignore_index=True)


def _improvement(value, reference):
    return (1 - value / reference) * 100 if np.isfinite(value) and np.isfinite(reference) and reference else np.nan


REFERENCES = {"vs_4w": "baseline", "vs_lastweek": "baseline_lastweek", "vs_mean4w": "q_mean4w"}


def improvement_tables(hourly: pd.DataFrame, daily: pd.DataFrame, city: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Headline per split/model on the hourly-model universe, and per-stratum improvements (%).

    For q, vs_4w is rule R (q of the 4-week mean curve), vs_lastweek rule A, vs_mean4w rule B.
    """
    rows = []
    for split in [s for s in ["validation", "test"] if s in set(daily.split)]:
        h = hourly.query("split == @split and dimension == 'overall'").set_index("model")
        d = daily.query("split == @split and dimension == 'overall'").set_index("model")
        c = city.query("split == @split and dimension == 'overall'").set_index("model")
        h_sum = h.departures_mae + h.returns_mae
        for model in d.index:
            row = dict(split=split, model=model, label=LABELS[model], oracle=model in ORACLE_MODELS)
            if model in h_sum.index:
                row["hourly_mae_sum"] = h_sum[model]
                row["hourly_improvement_vs_4w_pct"] = _improvement(h_sum[model], h_sum["baseline"])
                row["hourly_improvement_vs_lastweek_pct"] = _improvement(h_sum[model], h_sum["baseline_lastweek"])
            for metric in ["departures_day_mae", "departures_day_wape", "departures_day_within2", "returns_day_mae",
                           "netflow_day_mae", "q_mae", "q_bias", "q_under_rate", "q_within2", "q_wape", "qx_mae"]:
                row[metric] = d.loc[model, metric]
            for name, reference in REFERENCES.items():
                if name != "vs_mean4w":
                    row[f"departures_day_improvement_{name}_pct"] = _improvement(d.loc[model, "departures_day_mae"],
                                                                                 d.loc[reference, "departures_day_mae"])
                row[f"q_improvement_{name}_pct"] = _improvement(d.loc[model, "q_mae"], d.loc[reference, "q_mae"])
            for metric in ["city_departures_mape", "city_departures_bias_pct", "city_q_mape", "city_q_bias_pct"]:
                row[metric] = c.loc[model, metric]
            rows.append(row)
    groups = []
    for unit, table, dimensions, metric_columns in [
            ("hourly", hourly, ["hour", "activity", "day_type", "rain_day", "district"],
             {"hourly_mae_sum": ["departures_mae", "returns_mae"]}),
            ("station_day", daily, ["activity_stratum", "day_type", "rain_day", "district", "major_holiday_window", "month"],
             {"departures_day_mae": ["departures_day_mae"], "q_mae": ["q_mae"]})]:
        for metric, parts in metric_columns.items():
            frame = table[table.dimension.isin(dimensions)].copy()
            frame["value"] = frame[parts].sum(axis=1, min_count=len(parts))
            pivot = frame.pivot_table(index=["split", "dimension", "group_value"], columns="model", values="value", aggfunc="first")
            counts = frame[frame.model.eq("baseline")].set_index(["split", "dimension", "group_value"])[
                "n_hours" if unit == "hourly" else "n_station_days"].reindex(pivot.index).to_numpy()
            for model in pivot.columns:
                if model in REFERENCES.values() or pivot[model].isna().all():
                    continue
                part = pd.DataFrame({"unit": unit, "metric": metric, "model": model, "label": LABELS[model],
                                     "n": counts, "value": pivot[model]})
                for name, reference in REFERENCES.items():
                    if reference in pivot:
                        part[f"ref_{name}"] = pivot[reference]
                        part[f"improvement_{name}_pct"] = (1 - part.value / pivot[reference]) * 100
                groups.append(part.reset_index())
    return pd.DataFrame(rows), pd.concat(groups, ignore_index=True)


def summary_tables(output_dir: Path) -> str:
    """Markdown tables of the published metrics (numbers are code output only)."""
    output_dir = Path(output_dir)
    summary = pd.read_csv(output_dir / "improvement_summary.csv")
    groups = pd.read_csv(output_dir / "improvement_by_group.csv", dtype={"group_value": str})
    qm = pd.read_csv(output_dir / "q_model_metrics.csv", dtype={"group_value": str})
    selection = json.loads((output_dir / "model_selection.json").read_text(encoding="utf-8"))
    hourly_model, q_ai = selection["chosen_model"], selection["q_ai_model"]
    fmt = lambda v, p=3: "" if pd.isna(v) else f"{v:.{p}f}"
    pct = lambda v: "" if pd.isna(v) else f"{v:+.1f}%"
    share = lambda v: "" if pd.isna(v) else f"{v * 100:.1f}%"
    lines = [f"검증 잠금 선택: 시간 곡선 `{hourly_model}`, q 직접 모형(q_ai) `{q_ai}`", "",
             "## 1. 시간대 모형과 거점·일 결정 단위(시간 모형 적용 거점·일)", ""]
    for split in ["validation", "test"]:
        part = summary[summary.split.eq(split)]
        lines += [f"### {split}", "",
                  "| 모형 | 시간 MAE합 | 개선(4주) | 거점·일 대여 MAE | 개선(4주) | 개선(지난주) | 대여 ±2대 | 시 전체 일 대여 오차율 "
                  "| q MAE | 개선 R | 개선 B | 개선 A | q ±2대 | q 과소율 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for _, r in part.iterrows():
            lines.append("| " + " | ".join([
                Q_LABELS[r.model] if r.model == "baseline" else r.label, fmt(r.hourly_mae_sum),
                pct(r.hourly_improvement_vs_4w_pct), fmt(r.departures_day_mae),
                pct(r.departures_day_improvement_vs_4w_pct), pct(r.departures_day_improvement_vs_lastweek_pct),
                share(r.departures_day_within2), "" if pd.isna(r.city_departures_mape) else f"{r.city_departures_mape:.2f}%",
                fmt(r.q_mae), pct(r.q_improvement_vs_4w_pct), pct(r.q_improvement_vs_mean4w_pct),
                pct(r.q_improvement_vs_lastweek_pct), share(r.q_within2), share(r.q_under_rate)]) + " |")
        lines.append("")
    shown = list(dict.fromkeys(["baseline", "q_mean4w", "baseline_lastweek", q_ai, "qgb_oracle_weather"]))
    lines += ["## 2. 거점·일 필요 대수 q(직전 28일 활동 거점 전부, q_pred 파일과 같은 대상)", "",
              "| 구분 | 모형 | n | q MAE | 개선 R | 개선 B | 과소율 | 과소 대수 | ±2대 | 평균 편향 |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for split in ["validation", "test"]:
        overall = qm[qm.split.eq(split) & qm.dimension.eq("overall")].set_index("model")
        for model in shown:
            r = overall.loc[model]
            lines.append("| " + " | ".join([
                split, Q_LABELS[model], str(int(r.n_station_days)), fmt(r.q_mae),
                pct(_improvement(r.q_mae, overall.loc["baseline", "q_mae"])),
                pct(_improvement(r.q_mae, overall.loc["q_mean4w", "q_mae"])),
                share(r.q_under_rate), fmt(r.q_under_units), share(r.q_within2), fmt(r.q_bias)]) + " |")
    lines += ["", "## 3. 어디서 개선·악화되는가: q MAE 개선율(규칙R 대비, 직전 28일 활동 거점 전부)", "",
              f"| 구분 | 층 | n(시험) | {Q_LABELS[q_ai]} 검증 | 시험 | 오라클 검증 | 시험 |", "|---|---|---:|---:|---:|---:|---:|"]
    strata = qm[qm.dimension.isin(["activity_stratum", "day_type", "rain_day", "major_holiday_window",
                                   "station_age_group", "rule4w_band", "district"])]
    for (dimension, group), block in strata.groupby(["dimension", "group_value"], sort=True):
        cells = []
        for model in [q_ai, "qgb_oracle_weather"]:
            for split in ["validation", "test"]:
                b = block[block.split.eq(split)].set_index("model")
                cells.append(pct(_improvement(b.loc[model, "q_mae"], b.loc["baseline", "q_mae"])) if model in b.index else "")
        n_test = block[block.split.eq("test") & block.model.eq("baseline")].n_station_days
        lines.append(f"| {dimension} | {group} | {int(n_test.iloc[0]) if len(n_test) else ''} | " + " | ".join(cells) + " |")
    lines.append("")
    for unit, metric, title, models in [
            ("hourly", "hourly_mae_sum", "4. 시간 MAE합 개선율(4주 기준선 대비)", [hourly_model, "gb_oracle_weather"]),
            ("station_day", "departures_day_mae", "5. 거점·일 대여 MAE 개선율(4주 기준선 대비)", [hourly_model, "gb_oracle_weather"])]:
        part = groups[groups.unit.eq(unit) & groups.metric.eq(metric) & groups.model.isin(models)]
        models = [m for m in dict.fromkeys(models) if m in set(part.model)]
        if not models:
            continue
        lines += [f"## {title}", "", "| 구분 | 층 | n(시험) | " + " | ".join(f"{LABELS[m]} 검증 | 시험" for m in models) + " |",
                  "|---|---|---:|" + "---:|" * (2 * len(models))]
        for (dimension, group), block in part.groupby(["dimension", "group_value"], sort=True):
            if dimension == "hour" and int(group) % 3:
                continue
            cells = []
            for model in models:
                for split in ["validation", "test"]:
                    cell = block[block.model.eq(model) & block.split.eq(split)].improvement_vs_4w_pct
                    cells.append(pct(cell.iloc[0]) if len(cell) else "")
            n_test = block[block.split.eq("test")].n
            lines.append(f"| {dimension} | {group} | {int(n_test.iloc[0]) if len(n_test) and pd.notna(n_test.iloc[0]) else ''} | "
                         + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- pipeline helpers

def _write_split(features, stage: Path, split: str, fitted: dict, district_map: pd.DataFrame,
                 hourly_ctx: pd.DataFrame, day_labels: pd.DataFrame) -> dict:
    """Predict fixed models in bounded batches; observations update only via lags."""
    start, end = SPLITS[split]
    con = _connection()
    paths = _paths(features)
    actual_path, pred_path = stage / f"actuals_{split}.parquet", stage / f"predictions_{split}.parquet"
    try:
        con.register("district_map", district_map)
        con.register("day_labels", day_labels)
        con.execute(f"""COPY (SELECT f.station_id,f.event_time,f.cutoff,f.departures,f.returns,
            f.activity_stratum,f.history_stratum,coalesce(d.district,'unmatched_historical_id') district,
            l.day_type,l.rain_day
            FROM read_parquet({paths}) f LEFT JOIN district_map d
                ON f.station_id=d.station_id AND year(f.event_time)=d.year
            LEFT JOIN day_labels l ON f.cutoff=l.target_date
            WHERE f.cutoff BETWEEN DATE '{start}' AND DATE '{end}'
            ORDER BY f.event_time,f.station_id) TO {_path(actual_path)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
        bad = con.execute(f"""SELECT count(*) FILTER (WHERE day_type IS NULL OR rain_day IS NULL),
            count(*) FILTER (WHERE cutoff < DATE '{start}' OR cutoff > DATE '{end}')
            FROM read_parquet({_path(actual_path)})""").fetchone()
        if any(bad):
            raise ValueError(f"{split} actuals outside split or missing day labels: {bad}")
        reader = con.execute(f"SELECT * FROM read_parquet({paths}) WHERE cutoff BETWEEN DATE '{start}' AND DATE '{end}' ORDER BY event_time,station_id").to_arrow_reader(batch_size=150000)
        writer = None
        counts = dict.fromkeys(HOURLY_MODELS, 0)
        try:
            for batch in reader:
                frame = add_context(batch.to_pandas(), hourly_ctx)
                for model in HOURLY_MODELS:
                    pred = _predict(frame, model, fitted)
                    counts[model] += len(pred)
                    table = pa.Table.from_pandas(pred, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(pred_path, table.schema, compression="zstd")
                    writer.write_table(table)
        finally:
            if writer is not None:
                writer.close()
        return counts
    finally:
        con.close()


def _train_hourly(feature_paths, hourly_ctx: pd.DataFrame) -> tuple[dict, int, dict]:
    """One Fortran-ordered matrix of every hourly input; each model fits a column prefix."""
    glob = _paths(feature_paths)
    where = f"cutoff <= DATE '{SPLITS['train'][1]}'"
    con = _connection()
    try:
        n, low, high = con.execute(f"SELECT count(*), min(cutoff), max(cutoff) FROM read_parquet({glob}) WHERE {where}").fetchone()
        if pd.Timestamp(low) < pd.Timestamp(SPLITS["train"][0]) or pd.Timestamp(high) > pd.Timestamp(SPLITS["train"][1]):
            raise ValueError("training rows outside the training split")
        matrix = np.empty((n, len(ALL_HOURLY)), dtype=np.float64, order="F")
        targets = {t: np.empty(n, dtype=np.float64) for t in TARGETS}
        context = hourly_ctx[CONTEXT_HOURLY].to_numpy(dtype=np.float64)
        # Same scan as v1 (file order), so hist_gb_poisson sees identical rows in identical order.
        reader = con.execute(f"SELECT event_time,{','.join(FEATURES + TARGETS)} FROM read_parquet({glob}) WHERE {where}").to_arrow_reader(batch_size=200000)
        position = 0
        for batch in reader:
            k = batch.num_rows
            for j, feature in enumerate(FEATURES):
                matrix[position:position + k, j] = batch.column(feature).to_numpy(zero_copy_only=False)
            matrix[position:position + k, len(FEATURES):] = context[_context_index(batch.column("event_time").to_numpy(zero_copy_only=False), hourly_ctx.index)]
            for target in TARGETS:
                targets[target][position:position + k] = batch.column(target).to_numpy(zero_copy_only=False)
            position += k
        if position != n:
            raise ValueError("training scan length changed")
    finally:
        con.close()
    _check_matrix(matrix, ALL_HOURLY)
    fitted, seconds = {}, {}
    for model, features in HOURLY_MODELS.items():
        if features is None:
            continue
        began = time.monotonic()
        print(f"fit {model}: {n} rows x {len(features)} inputs", flush=True)
        fitted[model] = _fit_targets(matrix[:, :len(features)], targets)
        seconds[model] = time.monotonic() - began
    del matrix, targets
    gc.collect()
    return fitted, n, seconds


def q_forecasts(table: pd.DataFrame, fitted: dict) -> pd.DataFrame:
    """Long station-day q forecasts: rules A/B/R and every direct GB model (incl. oracle)."""
    keys = table[["station_id", "target_date"]]
    frames = [keys.assign(model=model, q_raw=table[column].to_numpy(dtype=float)) for model, column in Q_RULES.items()]
    with threadpool_limits(limits=2):
        for model, features in DAILY_MODELS.items():
            estimator = fitted[model]["q"]
            values = np.full(len(table), estimator) if isinstance(estimator, float) else estimator.predict(_matrix(table, features))
            frames.append(keys.assign(model=model, q_raw=np.maximum(values, 0.0)))
    out = pd.concat(frames, ignore_index=True)
    if not np.isfinite(out.q_raw).all() or (out.q_raw < 0).any():
        raise ValueError("q forecasts must be finite and nonnegative")
    return out


def _comparison_frame(table: pd.DataFrame, forecasts: pd.DataFrame, pred_path: Path, start, end) -> pd.DataFrame:
    """Hourly-model universe: daily sums and 02~23h curve q of every hourly model, plus
    rule B and the direct q models on the same station-days."""
    keys = ["station_id", "target_date"]
    universe = table.loc[table.in_hourly_universe, keys + ["q_rule4w", "q_lag_7"] + LABEL_COLUMNS]
    frames = []
    for model in HOURLY_MODELS:
        aggregated = _daily_from_predictions(pred_path, start, end, model)
        merged = universe[keys].merge(aggregated, on=keys, how="outer", indicator=True, validate="one_to_one")
        if not merged._merge.eq("both").all():
            raise ValueError(f"{model}: hourly predictions do not match the eligible station-days")
        frames.append(merged.drop(columns="_merge").assign(
            model=model, q_raw=merged.q_curve_raw, pred_netflow_day=merged.pred_departures_day - merged.pred_returns_day))
    q_only = forecasts[forecasts.model.isin(["q_mean4w", *DAILY_MODELS])].merge(universe[keys], on=keys, how="inner")
    if len(q_only) != len(universe) * (1 + len(DAILY_MODELS)):
        raise ValueError("direct q forecasts do not cover the eligible station-days")
    out = pd.concat(frames + [q_only], ignore_index=True)
    # Two data paths must agree: hourly-model curves vs the station-day cube.
    check = universe[keys + ["q_rule4w", "q_lag_7"]].merge(
        out.loc[out.model.eq("baseline"), keys + ["q_raw"]], on=keys).merge(
        out.loc[out.model.eq("baseline_lastweek"), keys + ["q_raw"]], on=keys, suffixes=("", "_lastweek"))
    if len(check) != len(universe) or not (np.allclose(check.q_raw, check.q_rule4w, rtol=0, atol=1e-9)
                                           and np.allclose(check.q_raw_lastweek, check.q_lag_7, rtol=0, atol=1e-9)):
        raise ValueError("hourly baseline curves disagree with the station-day cube")
    return out.merge(universe[keys + LABEL_COLUMNS], on=keys, how="left", validate="many_to_one")


def _evaluate_split(split: str, table: pd.DataFrame, fitted: dict, stage: Path, district_map: pd.DataFrame,
                    exact_q: pd.DataFrame):
    start, end = SPLITS[split]
    keys = ["station_id", "target_date"]
    table = table.assign(year=table.target_date.dt.year).merge(district_map, on=["station_id", "year"], how="left").drop(columns="year")
    table["district"] = table.district.fillna("unmatched_historical_id")
    table = table.merge(exact_q[keys + ["q"]].rename(columns={"q": "q_exact"}), on=keys, how="left", validate="one_to_one")
    if table.q_exact.isna().any():
        raise ValueError("exact-timestamp q missing for an observed station-day")
    forecasts = q_forecasts(table, fitted)
    q_metrics = forecast_metrics(forecasts.merge(table[keys + LABEL_COLUMNS], on=keys, how="left", validate="many_to_one"),
                                 split, U_DIMENSIONS)
    comparison = _comparison_frame(table, forecasts, stage / f"predictions_{split}.parquet", start, end)
    con = _connection()
    try:  # cube day sums must equal the hourly actuals used for hourly scoring
        sums = con.execute(f"""SELECT station_id, CAST(cutoff AS TIMESTAMP) target_date, sum(departures) d, sum(returns) r
            FROM read_parquet({_path(stage / f'actuals_{split}.parquet')}) GROUP BY ALL""").fetchdf()
    finally:
        con.close()
    sums["target_date"] = pd.to_datetime(sums.target_date).astype("datetime64[ns]")
    check = table.loc[table.in_hourly_universe, keys + ["departures_day", "returns_day"]].merge(sums, on=keys, how="outer", indicator=True)
    if not (check._merge.eq("both").all() and check.d.eq(check.departures_day).all() and check.r.eq(check.returns_day).all()):
        raise ValueError("station-day cube disagrees with the hourly actuals")
    daily = forecast_metrics(comparison, split, E_DIMENSIONS)
    city_days, city = city_metrics(comparison, split)
    forecasts.to_parquet(stage / f"q_forecasts_{split}.parquet", index=False)
    table[keys + ["in_hourly_universe"] + LABEL_COLUMNS].to_parquet(stage / "scratch" / f"q_table_{split}.parquet", index=False)
    comparison[keys + ["model", "pred_departures_day", "pred_returns_day", "pred_netflow_day", "q_curve_raw", "q_raw"]].to_parquet(
        stage / f"daily_predictions_{split}.parquet", index=False)
    comparison.loc[comparison.model.eq("baseline"), keys + LABEL_COLUMNS].to_parquet(stage / f"daily_actuals_{split}.parquet", index=False)
    city_days.to_csv(stage / f"city_daily_{split}.csv", index=False, encoding="utf-8-sig")
    return daily, city, q_metrics


def _write_q_pred(stage: Path, split: str, q_ai_model: str) -> Path:
    """Simulator input: one row per station-day with activity in the prior 28 days."""
    keys = ["station_id", "target_date"]
    wide = pd.read_parquet(stage / f"q_forecasts_{split}.parquet").pivot(index=keys, columns="model", values="q_raw")
    table = pd.read_parquet(stage / "scratch" / f"q_table_{split}.parquet").set_index(keys)
    wide = wide.reindex(table.index)
    out = pd.DataFrame({"station_id": table.index.get_level_values(0).astype(np.int64),
                        "day": table.index.get_level_values(1).date,
                        "q_rule4w": wide["baseline"].to_numpy(), "q_ai": wide[q_ai_model].to_numpy(),
                        "q_ai_oracle_weather": wide["qgb_oracle_weather"].to_numpy(), "q_actual": table.q_actual.to_numpy(),
                        "q_rule_lastweek": wide["baseline_lastweek"].to_numpy(), "q_rule_mean4w": wide["q_mean4w"].to_numpy(),
                        "q_exact_timestamp": table.q_exact.to_numpy(), "in_hourly_universe": table.in_hourly_universe.to_numpy()})
    out = out.sort_values(["day", "station_id"]).reset_index(drop=True)
    if out.isna().any().any() or out.duplicated(["station_id", "day"]).any():
        raise ValueError("q_pred must have one complete row per station-day")
    path = stage / f"q_pred_{split}.parquet"
    out.to_parquet(path, index=False)
    return path


def _completeness(con, masks_path: Path, stage: Path, split: str) -> list[dict]:
    start, end = SPLITS[split]
    actual, pred = stage / f"actuals_{split}.parquet", stage / f"predictions_{split}.parquet"
    hourly_days, active_days = con.execute(f"""SELECT count(*) FILTER (WHERE eligible_asof AND history_complete_28),
        count(*) FILTER (WHERE coverage_status='{OBSERVED}' AND observed_activity_prior_28d)
        FROM read_parquet({_path(masks_path)}) WHERE target_date BETWEEN DATE '{start}' AND DATE '{end}'""").fetchone()
    expected = hourly_days * 24
    actual_n, days = con.execute(f"SELECT count(*),count(DISTINCT cutoff) FROM read_parquet({_path(actual)})").fetchone()
    expected_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    rows = []
    for model in HOURLY_MODELS:
        n, distinct_n, invalid, bad_cutoff = con.execute(f"""SELECT count(*),count(DISTINCT (station_id,event_time,cutoff,model)),
            count(*) FILTER (WHERE NOT isfinite(pred_departures) OR NOT isfinite(pred_returns) OR pred_departures<0 OR pred_returns<0),
            count(*) FILTER (WHERE cutoff != date_trunc('day',event_time))
            FROM read_parquet({_path(pred)}) WHERE model='{model}'""").fetchone()
        missing = con.execute(f"""SELECT count(*) FROM read_parquet({_path(actual)}) a ANTI JOIN
            (SELECT * FROM read_parquet({_path(pred)}) WHERE model='{model}') p USING(station_id,event_time,cutoff)""").fetchone()[0]
        rows.append(dict(split=split, unit="hourly", model=model, expected_rows=expected, actual_rows=actual_n,
                         prediction_rows=n, missing_predictions=missing, days=days, expected_days=expected_days,
                         duplicate_keys=n - distinct_n, invalid_predictions=invalid, invalid_cutoffs=bad_cutoff))
        if n != expected or actual_n != expected or days != expected_days or missing or invalid or bad_cutoff or n != distinct_n:
            raise ValueError(f"Incomplete {split}/{model}: {rows[-1]}")
    for unit, path, expected_rows, models in [
            ("station_day_hourly_universe", stage / f"daily_predictions_{split}.parquet", hourly_days,
             list(HOURLY_MODELS) + ["q_mean4w", *DAILY_MODELS]),
            ("station_day_active_28d", stage / f"q_forecasts_{split}.parquet", active_days, list(Q_RULES) + list(DAILY_MODELS))]:
        for model in models:
            n, distinct_n, invalid, n_days = con.execute(f"""SELECT count(*), count(DISTINCT (station_id,target_date)),
                count(*) FILTER (WHERE q_raw IS NULL OR NOT isfinite(q_raw) OR q_raw<0), count(DISTINCT target_date)
                FROM read_parquet({_path(path)}) WHERE model='{model}'""").fetchone()
            rows.append(dict(split=split, unit=unit, model=model, expected_rows=expected_rows, actual_rows=expected_rows,
                             prediction_rows=n, missing_predictions=expected_rows - distinct_n, days=n_days,
                             expected_days=expected_days, duplicate_keys=n - distinct_n, invalid_predictions=invalid,
                             invalid_cutoffs=0))
            if n != expected_rows or distinct_n != n or invalid or n_days != expected_days:
                raise ValueError(f"Incomplete {unit} {split}/{model}: {rows[-1]}")
    return rows


def _memory() -> dict:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ["PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage"]]

        info = ProcessMemoryCounters()
        info.cb = ctypes.sizeof(info)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(info), info.cb):
            return {"measurement": "unavailable"}
        return {"measurement": "Windows GetProcessMemoryInfo; process lifetime OS peak working set",
                "working_set_bytes": info.WorkingSetSize, "peak_working_set_bytes": info.PeakWorkingSetSize}
    return {"measurement": "unavailable on this platform"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_inputs(root: Path = ROOT) -> dict:
    raw, panel = root / "data/raw", root / "data/processed/event_panel"
    return {"panel": [panel / f"hourly_panel_{y}.parquet" for y in [2023, 2024, 2025]],
            "events": [panel / f"exact_events_{y}.parquet" for y in [2023, 2024, 2025]],
            "masks": panel / "station_day_masks.parquet",
            "stations": raw / "nubija_stations/nubija_stations_2023_2025.xlsx",
            "calendar": [raw / f"calendar/kasi_calendarData_{y}.txt" for y in [2023, 2024, 2025]],
            "weather_hourly": raw / "weather/kma_asos_2023_2025/20261016T150911Z/asos155_hourly_2023_2025.csv",
            "weather_daily": [raw / f"approved_public_apis/20261016T150727234763Z/derived_csv/asos155_daily_{y}.csv" for y in [2023, 2024, 2025]],
            "task4_validation_q": root / "data/processed/support_policies/observed_q_validation.parquet"}


def _label(path: Path) -> str:
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()


def _validation_inputs(inputs: dict) -> list[Path]:
    """Every file phase 'validation' may read. 2025 bike files are deliberately absent."""
    files = inputs["panel"][:2] + inputs["events"][:2] + [inputs["masks"], inputs["stations"], inputs["weather_hourly"]]
    files += list(inputs["calendar"]) + list(inputs["weather_daily"])
    if inputs.get("task4_validation_q") and Path(inputs["task4_validation_q"]).exists():
        files.append(inputs["task4_validation_q"])
    return [Path(p) for p in files]


def _context(inputs: dict):
    holidays = kasi_holidays(inputs["calendar"])
    hourly_wx, daily_wx = weather_tables(inputs["weather_hourly"], inputs["weather_daily"])
    daily_ctx, hourly_ctx = context_tables(holidays, hourly_wx, daily_wx, SPLITS["train"][0], SPLITS["test"][1])
    return daily_ctx, hourly_ctx


def _context_hash(daily_ctx: pd.DataFrame, hourly_ctx: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(pd.util.hash_pandas_object(daily_ctx.reset_index(), index=False).to_numpy().tobytes())
    digest.update(pd.util.hash_pandas_object(hourly_ctx.reset_index(), index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _set_spill(stage: Path) -> None:
    global _SPILL_DIRECTORY
    _SPILL_DIRECTORY = stage / "scratch" / "duckdb-spill"


def _environment() -> dict:
    return dict(python=platform.python_version(), threads=2, duckdb_memory_limit="768MB",
                dependencies={"numpy": np.__version__, "pandas": pd.__version__, "scikit-learn": sklearn.__version__,
                              "scipy": scipy.__version__, "duckdb": duckdb.__version__, "pyarrow": pa.__version__})


def run_validation_phase(inputs: dict, stage: Path) -> dict:
    """Fit on train, score validation, select and lock. Never reads a 2025 bike file."""
    began = time.monotonic()
    stage = Path(stage).resolve()
    if stage.exists():
        raise FileExistsError(f"Stage already exists: {stage}")
    stage.mkdir(parents=True)
    scratch = stage / "scratch"
    scratch.mkdir()
    _set_spill(stage)
    audit = dict(protocol=PROTOCOL, phase="validation", model_parameters=MODEL_PARAMS, splits=SPLITS,
                 environment=_environment(), stages_seconds={}, memory_samples={})
    try:
        audit["inputs_sha256"] = {_label(p): _sha256(p) for p in _validation_inputs(inputs)}
        # Bytes only, never parsed here: lets phase 'test' prove 2025 files did not change.
        audit["test_inputs_sha256"] = {_label(p): (_sha256(p) if Path(p).exists() else None)
                                       for p in [inputs["panel"][2], inputs["events"][2]]}
        step = time.monotonic()
        daily_ctx, hourly_ctx = _context(inputs)
        audit["context_sha256"] = _context_hash(daily_ctx, hourly_ctx)
        feature_paths = []
        for year in [2023, 2024]:
            print(f"features {year}", flush=True)
            path = scratch / f"features_{year}.parquet"
            build_feature_parquet(inputs["panel"][:2], inputs["masks"], path, f"{year}-01-01", f"{year}-12-31")
            feature_paths.append(path)
        cube = hourly_cube(inputs["panel"][:2], SPLITS["train"][0], SPLITS["validation"][1])
        train_table = daily_table(cube, inputs["masks"], daily_ctx, *SPLITS["train"], strict=False)
        validation_table = daily_table(cube, inputs["masks"], daily_ctx, *SPLITS["validation"])
        del cube
        audit["stages_seconds"]["features"] = time.monotonic() - step
        step = time.monotonic()
        print("exact-timestamp q 2023-2024", flush=True)
        qtable = observed_daily_q(inputs["events"][:2], inputs["masks"], "2023-01-01", "2024-12-31")
        qtable.to_parquet(scratch / "observed_q_2023_2024.parquet", index=False)
        check = Path(inputs.get("task4_validation_q") or "")
        if check.is_file():
            reference = pd.read_parquet(check, columns=["station_id", "target_date", "q"])
            reference["target_date"] = pd.to_datetime(reference.target_date).astype("datetime64[ns]")
            joined = reference.merge(qtable, on=["station_id", "target_date"], how="left", suffixes=("_task4", ""))
            mismatches = int((joined.q.isna() | joined.q.ne(joined.q_task4)).sum())
            audit["task4_q_crosscheck"] = dict(rows=len(reference), mismatches=mismatches)
            if mismatches:
                raise ValueError(f"exact q differs from Task 4 validation q in {mismatches} rows")
        audit["stages_seconds"]["exact_q"] = time.monotonic() - step
        audit["memory_samples"]["features"] = _memory()
        step = time.monotonic()
        fitted, audit["training_rows"], audit["fit_seconds"] = _train_hourly(feature_paths, hourly_ctx)
        audit["daily_training_rows"] = len(train_table)
        for model, features in DAILY_MODELS.items():
            print(f"fit {model}: {len(train_table)} station-days x {len(features)} inputs", flush=True)
            fitted[model] = _fit_targets(_matrix(train_table, features), {"q": train_table.q_actual})
        del train_table
        audit["stages_seconds"]["fit"] = time.monotonic() - step
        audit["model_iterations"] = {m: {t: (int(v.n_iter_) if not isinstance(v, float) else 0) for t, v in f.items()}
                                     for m, f in fitted.items()}
        audit["memory_samples"]["fit"] = _memory()
        with (stage / "fitted_models.pkl").open("wb") as handle:
            pickle.dump(fitted, handle, protocol=pickle.HIGHEST_PROTOCOL)
        step = time.monotonic()
        print("predict validation", flush=True)
        district_map = district_reference(inputs["stations"])
        day_labels = daily_ctx.reset_index()[["target_date", "day_type", "rain_day"]]
        _write_split(feature_paths, stage, "validation", fitted, district_map, hourly_ctx, day_labels)
        hourly = _score_parquet(stage / "predictions_validation.parquet", stage / "actuals_validation.parquet", "validation")
        daily, city, q_metrics = _evaluate_split("validation", validation_table, fitted, stage, district_map, qtable)
        audit["stages_seconds"]["validation"] = time.monotonic() - step
        for name, frame in [("metrics", hourly), ("daily_metrics", daily), ("city_metrics", city), ("q_model_metrics", q_metrics)]:
            frame.to_csv(scratch / f"{name}_validation.csv", index=False, encoding="utf-8-sig", na_rep="NaN")
        overall_h = hourly.query("dimension == 'overall'").set_index("model")
        overall_q = q_metrics.query("dimension == 'overall'").set_index("model")
        overall_e = daily.query("dimension == 'overall'").set_index("model")
        hourly_scores = {m: float(overall_h.loc[m, "departures_mae"] + overall_h.loc[m, "returns_mae"]) for m in HOURLY_MODELS}
        chosen = select_model({m: hourly_scores[m] for m in HOURLY_SELECTION_ORDER}, HOURLY_SELECTION_ORDER)
        q_ai = select_model({m: float(overall_q.loc[m, "q_mae"]) for m in Q_AI_ORDER}, Q_AI_ORDER)
        # The lock is written BEFORE any 2025 file is opened.
        selection = dict(protocol=PROTOCOL, chosen_model=chosen, rule=HOURLY_RULE, validation_mae_sums=hourly_scores,
                         q_ai_model=q_ai, q_ai_rule=Q_AI_RULE,
                         validation_q_mae_active_28d={m: float(v) for m, v in overall_q.q_mae.items()},
                         validation_q_mae_hourly_universe={m: float(v) for m, v in overall_e.q_mae.items()},
                         q_definition="max_k(sum_{h<=k} dep_h - sum_{h<k} ret_h), hours 02~23 of the day, >= 0 "
                                      "(simulate_rebalancing.q_from_hourly); exact-timestamp q kept as q_exact",
                         oracle_models_not_selectable=sorted(ORACLE_MODELS),
                         policy_interface="selected_predictions_*.parquet = chosen_model hourly curves (Task 4 schema); "
                                          "q_pred_*.parquet = station-day q (q_ai = q_ai_model)",
                         model_parameters=MODEL_PARAMS, features=HOURLY_MODELS[chosen] or [],
                         feature_sets=dict(HOURLY_MODELS), daily_feature_sets=DAILY_MODELS,
                         feature_availability=AVAILABILITY, holiday_supplement=HOLIDAY_SUPPLEMENT, splits=SPLITS,
                         selection_time_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                         test_predictions_created=False, test_scores_viewed=False,
                         code_sha256=_sha256(Path(__file__)), inputs_sha256=audit["inputs_sha256"],
                         test_inputs_sha256=audit["test_inputs_sha256"], context_sha256=audit["context_sha256"],
                         fitted_models_sha256=_sha256(stage / "fitted_models.pkl"), prior_test_exposure=PRIOR_TEST_EXPOSURE)
        (stage / "model_selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
        audit["selection_sha256"] = _sha256(stage / "model_selection.json")
        (stage / "model_selection.sha256").write_text(audit["selection_sha256"] + "\n", encoding="ascii")
        audit["chosen_model"], audit["q_ai_model"] = chosen, q_ai
        audit["memory_samples"]["validation"] = _memory()
        audit["elapsed_seconds"] = time.monotonic() - began
        audit["completed_time_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (stage / "audit_validation.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"selection LOCKED sha256={audit['selection_sha256']}: hourly={chosen} q_ai={q_ai}", flush=True)
        return audit
    except Exception as exc:
        (stage / "FAILED.json").write_text(json.dumps({"phase": "validation", "error": repr(exc), "output_not_published": True},
                                                      ensure_ascii=False), encoding="utf-8")
        raise


def _verify_lock(inputs: dict, stage: Path) -> dict:
    lock_path = stage / "model_selection.json"
    recorded = (stage / "model_selection.sha256").read_text(encoding="ascii").strip()
    if _sha256(lock_path) != recorded:
        raise ValueError("model_selection.json changed after the lock")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock["code_sha256"] != _sha256(Path(__file__)):
        raise ValueError("forecast code changed after the lock")
    for path in _validation_inputs(inputs):
        if lock["inputs_sha256"].get(_label(path)) != _sha256(path):
            raise ValueError(f"locked input changed: {_label(path)}")
    for path in [inputs["panel"][2], inputs["events"][2]]:
        expected = lock["test_inputs_sha256"].get(_label(path))
        if expected is not None and expected != _sha256(path):
            raise ValueError(f"test input changed after the lock: {_label(path)}")
    if lock["fitted_models_sha256"] != _sha256(stage / "fitted_models.pkl"):
        raise ValueError("fitted models changed after the lock")
    return lock


def _publish(files: list[Path], output: Path, archive_name: str) -> dict:
    """Copy existing outputs to output/archive_name (hash-verified), then replace files."""
    output = Path(output)
    archived = {}
    if output.exists():
        archive = output / archive_name
        if archive.exists():
            raise FileExistsError(f"Archive already exists: {archive}")
        previous = sorted(p for p in output.iterdir() if p.is_file())
        archive.mkdir()
        for path in previous:
            shutil.copy2(path, archive / path.name)
            if _sha256(archive / path.name) != _sha256(path):
                raise ValueError(f"archive copy differs: {path.name}")
            archived[path.name] = _sha256(path)
    else:
        output.mkdir(parents=True)
    for path in files:
        temporary = output / f".{path.name}.tmp"
        shutil.copy2(path, temporary)
        os.replace(temporary, output / path.name)
    return archived


def run_test_phase(inputs: dict, stage: Path, output: Path, archive_name: str = "_archive_20261017") -> dict:
    """Verify the lock, open 2025-01..06 once with fixed models, score and publish."""
    began = time.monotonic()
    stage = Path(stage).resolve()
    _set_spill(stage)
    scratch = stage / "scratch"
    lock = _verify_lock(inputs, stage)
    opening = stage / "test_opening.json"
    attempts = json.loads(opening.read_text(encoding="utf-8")) if opening.exists() else []
    if any(a["status"] == "scored" for a in attempts):
        raise ValueError("test already opened and scored for this lock")
    attempts.append({"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "opening"})
    opening.write_text(json.dumps(attempts, indent=2), encoding="utf-8")
    audit = json.loads((stage / "audit_validation.json").read_text(encoding="utf-8"))
    audit.update(phase="test", stages_seconds_test={}, test_opening_attempts=len(attempts))
    try:
        for path in [inputs["panel"][2], inputs["events"][2]]:
            if lock["test_inputs_sha256"].get(_label(path)) is None:
                audit.setdefault("test_inputs_hashed_at_opening", {})[_label(path)] = _sha256(path)
        # Safe: this pickle was written by phase 'validation' into our own stage and its
        # SHA-256 was just verified against the lock (_verify_lock) before loading.
        with (stage / "fitted_models.pkl").open("rb") as handle:
            fitted = pickle.load(handle)
        daily_ctx, hourly_ctx = _context(inputs)
        if _context_hash(daily_ctx, hourly_ctx) != lock["context_sha256"]:
            raise ValueError("context tables differ from the lock")
        step = time.monotonic()
        print("features 2025 (test opening)", flush=True)
        test_features = scratch / "features_2025.parquet"
        build_feature_parquet(inputs["panel"][1:], inputs["masks"], test_features, *SPLITS["test"])
        cube = hourly_cube(inputs["panel"], SPLITS["train"][0], SPLITS["test"][1])
        test_table = daily_table(cube, inputs["masks"], daily_ctx, *SPLITS["test"])
        del cube
        qtable = pd.concat([pd.read_parquet(scratch / "observed_q_2023_2024.parquet"),
                            observed_daily_q(inputs["events"][2:], inputs["masks"], *SPLITS["test"])], ignore_index=True)
        audit["stages_seconds_test"]["features_and_q"] = time.monotonic() - step
        step = time.monotonic()
        district_map = district_reference(inputs["stations"])
        day_labels = daily_ctx.reset_index()[["target_date", "day_type", "rain_day"]]
        _write_split([test_features], stage, "test", fitted, district_map, hourly_ctx, day_labels)
        hourly_test = _score_parquet(stage / "predictions_test.parquet", stage / "actuals_test.parquet", "test")
        daily_test, city_test, q_test = _evaluate_split("test", test_table, fitted, stage, district_map, qtable)
        attempts[-1]["status"] = "scored"
        attempts[-1]["scored_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        opening.write_text(json.dumps(attempts, indent=2), encoding="utf-8")
        audit["stages_seconds_test"]["predict_and_score"] = time.monotonic() - step
        read = lambda name: pd.read_csv(scratch / f"{name}_validation.csv", encoding="utf-8-sig", dtype={"group_value": str})
        hourly = pd.concat([read("metrics"), hourly_test], ignore_index=True)
        daily = pd.concat([read("daily_metrics"), daily_test], ignore_index=True)
        city = pd.concat([read("city_metrics"), city_test], ignore_index=True)
        q_metrics = pd.concat([read("q_model_metrics"), q_test], ignore_index=True)
        for name, frame in [("metrics", hourly), ("daily_metrics", daily), ("city_metrics", city), ("q_model_metrics", q_metrics)]:
            frame.to_csv(stage / f"{name}.csv", index=False, encoding="utf-8-sig", na_rep="NaN")
        summary, groups = improvement_tables(hourly, daily, city)
        summary.to_csv(stage / "improvement_summary.csv", index=False, encoding="utf-8-sig", na_rep="NaN")
        groups.to_csv(stage / "improvement_by_group.csv", index=False, encoding="utf-8-sig", na_rep="NaN")
        qtable.to_parquet(stage / "observed_q_daily.parquet", index=False)
        daily_ctx.to_csv(stage / "context_daily.csv", encoding="utf-8-sig", na_rep="NaN")
        con = _connection()
        try:
            rows = []
            for split in ["validation", "test"]:
                checks = _completeness(con, inputs["masks"], stage, split)
                rows += checks
                expected = checks[0]["expected_rows"]  # eligible station-days x 24
                # Simulator inputs, same hourly schema: leak-free final model, oracle bound, 4-week baseline.
                for name, model in [(f"selected_predictions_{split}", lock["chosen_model"]),
                                    (f"predictions_{split}_oracle_weather", "gb_oracle_weather"),
                                    (f"predictions_{split}_baseline4w", "baseline")]:
                    path = stage / f"{name}.parquet"
                    con.execute(f"""COPY (SELECT * FROM read_parquet({_path(stage / f'predictions_{split}.parquet')})
                        WHERE model='{model}') TO {_path(path)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
                    n, distinct_n = con.execute(f"SELECT count(*), count(DISTINCT (station_id,event_time,cutoff)) FROM read_parquet({_path(path)})").fetchone()
                    missing = con.execute(f"""SELECT count(*) FROM read_parquet({_path(stage / f'actuals_{split}.parquet')}) a
                        ANTI JOIN read_parquet({_path(path)}) p USING(station_id,event_time,cutoff)""").fetchone()[0]
                    rows.append(dict(split=split, unit=f"file:{path.name}", model=model, expected_rows=expected, actual_rows=expected,
                                     prediction_rows=n, missing_predictions=missing, duplicate_keys=n - distinct_n))
                    if n != expected or missing or n != distinct_n or list(pq.read_schema(path).names) != PRED_COLUMNS:
                        raise ValueError(f"simulator input incomplete: {rows[-1]}")
                path = _write_q_pred(stage, split, lock["q_ai_model"])
                active = [r for r in checks if r["unit"] == "station_day_active_28d"][0]["expected_rows"]
                n = pq.read_metadata(path).num_rows
                rows.append(dict(split=split, unit=f"file:{path.name}", model=lock["q_ai_model"], expected_rows=active,
                                 actual_rows=active, prediction_rows=n, missing_predictions=active - n, duplicate_keys=0))
                if n != active:
                    raise ValueError(f"q_pred incomplete: {rows[-1]}")
            pd.DataFrame(rows).to_csv(stage / "prediction_completeness.csv", index=False)
            con.execute(f"""COPY (SELECT target_date,history_stratum,eligible_asof,history_complete_28,count(*) station_days
                FROM read_parquet({_path(inputs['masks'])}) WHERE target_date <= DATE '{SPLITS['test'][1]}'
                GROUP BY ALL ORDER BY target_date,history_stratum,eligible_asof,history_complete_28)
                TO {_path(stage / 'eligibility_summary.csv')} (HEADER, DELIMITER ',')""")
        finally:
            con.close()
        audit["headline_allowed"] = True
        audit["test_refits"] = 0
        audit["memory_samples"]["test"] = _memory()
        with threadpool_limits(limits=2):
            audit["threadpools"] = threadpool_info()
        audit["elapsed_seconds_test"] = time.monotonic() - began
        audit["completed_time_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        audit["prior_test_exposure"] = PRIOR_TEST_EXPOSURE
        audit["omitted"] = ["training-period fit metrics (v1 reported them; not needed for selection)",
                            "hyperparameter search (plan-fixed parameters for every GB model)"]
        published = sorted(p for p in stage.iterdir() if p.is_file() and p.suffix in {".parquet", ".csv", ".json", ".sha256"}
                           and p.name not in {"audit_validation.json", "test_opening.json", "FAILED.json"})
        audit["test_opening"] = attempts
        audit["outputs"] = {p.name: dict(bytes=p.stat().st_size, sha256=_sha256(p),
                                         **({"rows": pq.read_metadata(p).num_rows} if p.suffix == ".parquet" else {}))
                            for p in published}
        (stage / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (stage / "summary_tables.md").write_text(summary_tables(stage), encoding="utf-8")
        published += [stage / "audit.json", stage / "summary_tables.md"]
        archived = _publish(published, output, archive_name)
        if archived:
            (Path(output) / archive_name / "ARCHIVE.json").write_text(json.dumps(
                {"archived_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "reason": "previous outputs before v2 publish",
                 "files_sha256": archived}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": str(output), "chosen_model": lock["chosen_model"], "q_ai_model": lock["q_ai_model"],
                          "elapsed_seconds_test": audit["elapsed_seconds_test"]}, ensure_ascii=False), flush=True)
        return audit
    except Exception as exc:
        (stage / "FAILED.json").write_text(json.dumps({"phase": "test", "error": repr(exc), "output_not_published": True},
                                                      ensure_ascii=False), encoding="utf-8")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["validation", "test", "summary"], required=True)
    parser.add_argument("--stage", type=Path, default=ROOT / ".tmp/forecast_v2_stage")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/forecast")
    args = parser.parse_args()
    if args.phase == "validation":
        run_validation_phase(default_inputs(), args.stage)
    elif args.phase == "test":
        run_test_phase(default_inputs(), args.stage, args.output)
    else:
        print(summary_tables(args.output))
