"""Chunked Nubija event aggregation with explicit missingness and daily as-of masks.

Hourly targets use all valid nonnegative-duration completed records. Exact events
also carry the positive <=24h cohort fully enclosed by continuous observed dates.
No bicycle ID or paired individual trip is retained in any final output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import platform
import re
import shutil
import tempfile
import time

import duckdb
import numpy as np
import pandas as pd
import pyarrow


ROOT = Path(__file__).resolve().parents[2]
COLUMNS = ["자전거번호", "출발터미널", "출발일", "출발시간", "도착터미널", "도착일", "도착시간"]
OBSERVED = "observed_departure_date"
PANEL_COLUMNS = ["station_id", "event_time", "departures", "returns", "coverage_status", "eligible_asof"]


def _sql_path(path: Path) -> str:
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def _coverage(days: pd.DatetimeIndex, departure_days: Counter) -> pd.DataFrame:
    dates = pd.DataFrame({"date": days})
    dates["raw_departures"] = [departure_days.get(d, 0) for d in days]
    july = dates.date.between("2025-07-01", "2025-07-31")
    dates["coverage_status"] = np.where(july, "incomplete_missing_july",
                                        np.where(dates.raw_departures.gt(0), OBSERVED, "unobserved_date"))
    dates["observed_date"] = dates.coverage_status.eq(OBSERVED)
    dates["coverage_span"] = dates.observed_date.ne(dates.observed_date.shift()).cumsum()
    dates["left_edge_censored"] = dates.observed_date & ~dates.observed_date.shift(fill_value=False)
    dates["right_edge_censored"] = dates.observed_date & ~dates.observed_date.shift(-1, fill_value=False)
    return dates


def _daily_masks(daily: pd.DataFrame, coverage: pd.DataFrame, stations: list[str]) -> pd.DataFrame:
    days = pd.DatetimeIndex(coverage.date)
    observed = coverage.observed_date.to_numpy()
    observed_series = pd.Series(observed.astype(int), index=days)
    history_days = observed_series.shift(1, fill_value=0).rolling(28, min_periods=1).sum().astype(int).to_numpy()
    result = []
    for station in stations:
        events = daily[daily.station_id.eq(station)].set_index("date").events.reindex(days, fill_value=0)
        events.loc[~observed] = 0
        prior_activity = events.gt(0).astype(int).shift(1, fill_value=0).rolling(28, min_periods=1).sum()
        first = events[events.gt(0)].index.min()
        age = np.zeros(len(days), dtype=int) if pd.isna(first) else np.maximum((days - first).days, 0)
        established = age >= 28
        active = prior_activity.gt(0).to_numpy()
        strata = np.where(age == 0, "not_previously_observed", np.where(established, "established", "new_under_28d"))
        # The target day contributes neither the activity count nor first-seen age.
        frame = pd.DataFrame({"station_id": station, "target_date": days, "forecast_cutoff": days,
                              "coverage_status": coverage.coverage_status.to_numpy(),
                              "observed_date": observed, "observed_activity_prior_28d": active,
                              "history_days_since_first_observed": age,
                              "history_observed_dates_28": history_days,
                              "history_complete_28": history_days == 28,
                              "history_stratum": strata,
                              "eligible_asof": observed & active & established})
        result.append(frame)
    return pd.concat(result, ignore_index=True) if result else pd.DataFrame(columns=["station_id", "target_date", "eligible_asof"])


def run_pipeline(trip_paths: list[Path], start: str, end: str, output_dir: Path,
                 *, station_reference: Path | None = None, chunksize: int = 150000) -> dict:
    """Write verified outputs atomically into a previously absent output directory.

    ``start`` and ``end`` are inclusive local calendar dates. A private staging
    directory holds unlinked event fragments, never bicycle IDs. Existing outputs
    are deliberately not replaced; choose a fresh directory for a new run.
    """
    began = time.monotonic()
    first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if first > last or not trip_paths:
        raise ValueError("Nonempty sources and an increasing date range are required")
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}")
    resolved = [Path(p).resolve() for p in trip_paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("Duplicate source path would double count trips")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=output_dir.name + ".staging-", dir=output_dir.parent))
    scratch = stage / "scratch"
    scratch.mkdir()
    counts, reasons, departure_days, station_days = Counter(), Counter(), Counter(), Counter()
    unmatched, source_summaries = Counter(), []
    known_by_year = {}
    con = None
    fragment = 0
    try:
        if station_reference is not None:
            with pd.ExcelFile(station_reference) as excel:
                for sheet in excel.sheet_names:
                    match = re.search(r"20\d{2}", sheet)
                    if match:
                        ref = pd.read_excel(excel, sheet_name=sheet, dtype=str)
                        ids = ref["터미널번호"].str.strip()
                        if ids.duplicated().any():
                            raise ValueError("Duplicate terminal IDs in station reference")
                        known_by_year[int(match.group())] = set(ids)
        for path in resolved:
            before = path.stat()
            file_year_match = re.search(r"20\d{2}", path.stem)
            file_year = int(file_year_match.group()) if file_year_match else None
            source_count = Counter()
            date_limits = {}
            source_began = time.monotonic()
            for chunk in pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False, chunksize=chunksize):
                if list(chunk.columns) != COLUMNS:
                    raise ValueError(f"Seven-column source schema mismatch: {path.name}")
                counts["raw_rows"] += len(chunk)
                source_count["raw_rows"] += len(chunk)
                dep = pd.to_datetime(chunk["출발일"] + " " + chunk["출발시간"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
                ret = pd.to_datetime(chunk["도착일"] + " " + chunk["도착시간"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
                if file_year is not None:
                    source_count["departure_outside_file_year"] += int((dep.notna() & dep.dt.year.ne(file_year)).sum())
                    source_count["return_outside_file_year"] += int((ret.notna() & ret.dt.year.ne(file_year)).sum())
                for name, values in [("departure", dep), ("return", ret)]:
                    if values.notna().any():
                        lo, hi = values.min(), values.max()
                        old = date_limits.get(name, (lo, hi))
                        date_limits[name] = (min(old[0], lo), max(old[1], hi))
                departure_days.update({k: int(v) for k, v in dep.dt.normalize().value_counts().items()})
                seconds = (ret - dep).dt.total_seconds()
                origin, destination = chunk["출발터미널"].str.strip(), chunk["도착터미널"].str.strip()
                invalid_datetime = dep.isna() | ret.isna()
                missing_station = ~invalid_datetime & (origin.eq("") | destination.eq(""))
                negative = ~invalid_datetime & ~missing_station & seconds.lt(0)
                valid = ~(invalid_datetime | missing_station | negative)
                for name, mask in [("invalid_datetime", invalid_datetime), ("missing_station_id", missing_station),
                                   ("negative_duration", negative), ("zero_seconds", valid & seconds.eq(0)),
                                   ("over_24h", valid & seconds.gt(86400)),
                                   ("cross_calendar_day", valid & dep.dt.normalize().ne(ret.dt.normalize()))]:
                    reasons[name] += int(mask.sum())
                    source_count[name] += int(mask.sum())
                n = int(valid.sum())
                counts["clean_rows"] += n
                source_count["clean_rows"] += n
                if not n:
                    continue
                start_day, end_day = dep[valid].dt.normalize(), ret[valid].dt.normalize()
                candidate = seconds[valid].gt(0) & seconds[valid].le(86400)
                events = []
                for direction, times, ids in [("departures", dep[valid], origin[valid]), ("returns", ret[valid], destination[valid])]:
                    event_days = times.dt.normalize()
                    for (station, date), amount in pd.DataFrame({"station_id": ids, "date": event_days}).groupby(["station_id", "date"]).size().items():
                        station_days[(str(station), date)] += int(amount)
                    if known_by_year:
                        for year in event_days.dt.year.unique():
                            subset = event_days.dt.year.eq(year)
                            unknown = ids[subset & ~ids.isin(known_by_year.get(int(year), set()))]
                            for station, amount in unknown.value_counts().items():
                                unmatched[(int(year), direction, str(station), "reference_missing" if int(year) not in known_by_year else "unmatched")] += int(amount)
                    events.append(pd.DataFrame({"station_id": ids.to_numpy(), "event_time": times.to_numpy(),
                                                "departures": int(direction == "departures"), "returns": int(direction == "returns"),
                                                "main_candidate": candidate.to_numpy(), "trip_start_date": start_day.to_numpy(),
                                                "trip_end_date": end_day.to_numpy()}))
                pd.concat(events, ignore_index=True).to_parquet(scratch / f"events_{fragment:05d}.parquet", index=False)
                fragment += 1
            after = path.stat()
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                raise ValueError(f"Source changed during scan: {path.name}")
            summary = {"file": str(path), "bytes": before.st_size, "mtime_ns": before.st_mtime_ns,
                       **dict(source_count), "date_ranges": {k: [str(x) for x in v] for k, v in date_limits.items()},
                       "scan_seconds": round(time.monotonic() - source_began, 3)}
            source_summaries.append(summary)
            print(f"{path.name}: {source_count['raw_rows']:,} raw / {source_count['clean_rows']:,} clean", flush=True)
        if not fragment:
            raise ValueError("No valid completed records")
        coverage = _coverage(pd.date_range(first, last, freq="D"), departure_days)
        daily = pd.DataFrame([{"station_id": s, "date": d, "events": n} for (s, d), n in station_days.items()])
        stations = sorted(daily.station_id.unique())
        masks = _daily_masks(daily, coverage, stations)
        coverage.to_csv(stage / "date_coverage.csv", index=False, encoding="utf-8-sig")
        masks.to_parquet(stage / "station_day_masks.parquet", index=False)
        pd.DataFrame([{"event_calendar_year": y, "event": e, "station_id": s, "events": n, "reference_status": status}
                      for (y, e, s, status), n in sorted(unmatched.items())],
                     columns=["event_calendar_year", "event", "station_id", "events", "reference_status"]).to_csv(
                         stage / "unmatched_station_ids.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(source_summaries).to_csv(stage / "source_date_ranges.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame(sorted(reasons.items()), columns=["reason", "rows"]).to_csv(stage / "anomaly_counts.csv", index=False, encoding="utf-8-sig")
        con = duckdb.connect()
        con.execute("SET memory_limit='768MB'")
        con.execute("SET threads=2")
        con.execute(f"SET temp_directory={_sql_path(scratch / 'duckdb_tmp')}")
        con.register("coverage", coverage)
        con.register("masks", masks)
        con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet({_sql_path(scratch / 'events_*.parquet')})")
        con.execute("""CREATE VIEW tagged AS SELECT e.*,
            (e.main_candidate AND coalesce(a.observed_date,false) AND coalesce(b.observed_date,false)
             AND a.coverage_span=b.coverage_span) AS main_included
            FROM events e LEFT JOIN coverage a ON e.trip_start_date=a.date
            LEFT JOIN coverage b ON e.trip_end_date=b.date""")
        raw_events = con.execute("SELECT sum(departures),sum(returns) FROM events").fetchone()
        if counts["raw_rows"] != counts["clean_rows"] + sum(reasons[n] for n in ["invalid_datetime", "missing_station_id", "negative_duration"]):
            raise ValueError("Raw-to-clean row conservation failed")
        if raw_events != (counts["clean_rows"], counts["clean_rows"]):
            raise ValueError("Raw-to-clean event conservation failed")
        main_counts = con.execute("SELECT sum(departures),sum(returns) FROM tagged WHERE main_included").fetchone()
        main_counts = tuple(int(x or 0) for x in main_counts)
        all_in_range, observed_in_range, main_written = Counter(), Counter(), Counter()
        # Each year is written directly by DuckDB; no exact event table is loaded into Python.
        for year in range(first.year, last.year + 1):
            lo, hi = max(first, pd.Timestamp(year, 1, 1)), min(last + pd.Timedelta(days=1), pd.Timestamp(year + 1, 1, 1))
            where = f"event_time >= TIMESTAMP '{lo}' AND event_time < TIMESTAMP '{hi}'"
            exact_path = stage / f"exact_events_{year}.parquet"
            con.execute(f"""COPY (SELECT station_id,event_time,sum(departures)::INTEGER AS departures,
                sum(returns)::INTEGER AS returns,
                sum(CASE WHEN main_included THEN departures ELSE 0 END)::INTEGER AS main_departures,
                sum(CASE WHEN main_included THEN returns ELSE 0 END)::INTEGER AS main_returns,
                c.coverage_status
                FROM tagged t LEFT JOIN coverage c ON date_trunc('day',t.event_time)=c.date
                WHERE {where} GROUP BY station_id,event_time,c.coverage_status
                ORDER BY event_time,station_id) TO {_sql_path(exact_path)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
            sums = con.execute(f"SELECT sum(departures),sum(returns),sum(main_departures),sum(main_returns) FROM read_parquet({_sql_path(exact_path)})").fetchone()
            for i, name in enumerate(["departures", "returns"]):
                all_in_range[name] += int(sums[i] or 0)
                main_written[name] += int(sums[i+2] or 0)
            con.execute(f"CREATE OR REPLACE VIEW hourly AS SELECT station_id,date_trunc('hour',event_time) AS event_time,sum(departures) AS departures,sum(returns) AS returns FROM read_parquet({_sql_path(exact_path)}) GROUP BY station_id,date_trunc('hour',event_time)")
            panel_path = stage / f"hourly_panel_{year}.parquet"
            con.execute(f"""COPY (SELECT m.station_id, m.target_date + h.hour * INTERVAL '1 hour' AS event_time,
                CASE WHEN m.observed_date THEN coalesce(e.departures,0) ELSE NULL END::INTEGER AS departures,
                CASE WHEN m.observed_date THEN coalesce(e.returns,0) ELSE NULL END::INTEGER AS returns,
                m.coverage_status,m.eligible_asof
                FROM masks m CROSS JOIN range(24) h(hour) LEFT JOIN hourly e
                ON e.station_id=m.station_id AND e.event_time=m.target_date+h.hour*INTERVAL '1 hour'
                WHERE m.target_date >= TIMESTAMP '{lo}' AND m.target_date < TIMESTAMP '{hi}'
                ORDER BY event_time,m.station_id) TO {_sql_path(panel_path)} (FORMAT PARQUET,COMPRESSION ZSTD)""")
            sums = con.execute(f"SELECT sum(departures),sum(returns) FROM read_parquet({_sql_path(panel_path)})").fetchone()
            for i, name in enumerate(["departures", "returns"]):
                observed_in_range[name] += int(sums[i] or 0)
            print(f"{year}: exact events and hourly panel written", flush=True)
        if tuple(main_written[n] for n in ["departures", "returns"]) != main_counts:
            raise ValueError("Main-cohort departure/return conservation failed")
        range_expected = con.execute(f"SELECT sum(departures),sum(returns) FROM events WHERE event_time >= TIMESTAMP '{first}' AND event_time < TIMESTAMP '{last + pd.Timedelta(days=1)}'").fetchone()
        if tuple(all_in_range[n] for n in ["departures", "returns"]) != tuple(int(x or 0) for x in range_expected):
            raise ValueError("All-record exact event conservation failed")
        expected_observed = con.execute(f"SELECT sum(t.departures),sum(t.returns) FROM events t JOIN coverage c ON date_trunc('day',t.event_time)=c.date WHERE c.observed_date").fetchone()
        if tuple(observed_in_range[n] for n in ["departures", "returns"]) != tuple(int(x or 0) for x in expected_observed):
            raise ValueError("Observed hourly panel conservation failed")
        counts["main_rows"] = main_counts[0]
        reasons["main_excluded_zero_seconds"] = reasons["zero_seconds"]
        reasons["main_excluded_over_24h"] = reasons["over_24h"]
        reasons["main_excluded_gap_or_range_edge"] = counts["clean_rows"] - counts["main_rows"] - reasons["zero_seconds"] - reasons["over_24h"]
        pd.DataFrame(sorted(reasons.items()), columns=["reason", "rows"]).to_csv(stage / "anomaly_counts.csv", index=False, encoding="utf-8-sig")
        mask_summary = masks.groupby(["target_date", "coverage_status"], as_index=False).agg(
            candidate_stations=("station_id", "size"), eligible_stations=("eligible_asof", "sum"),
            active_prior_28d=("observed_activity_prior_28d", "sum"))
        new = masks.history_stratum.eq("new_under_28d").groupby(masks.target_date).sum()
        mask_summary["new_under_28d_stations"] = mask_summary.target_date.map(new).fillna(0).astype(int)
        mask_summary["excluded_stations"] = mask_summary.candidate_stations - mask_summary.eligible_stations
        mask_summary.to_csv(stage / "daily_mask_summary.csv", index=False, encoding="utf-8-sig")
        con.close()
        con = None
        shutil.rmtree(scratch)
        audit = {"created_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "start": str(first.date()),
                 "end": str(last.date()), **dict(counts), "anomalies": dict(reasons), "sources": source_summaries,
                 "stations": len(stations), "observed_dates": int(coverage.observed_date.sum()),
                 "unobserved_dates": int((~coverage.observed_date).sum()), "all_valid_events_in_range": dict(all_in_range),
                 "observed_hourly_events": dict(observed_in_range), "main_events": dict(main_written),
                 "masked_events_in_range": {n: all_in_range[n]-observed_in_range[n] for n in ["departures", "returns"]},
                 "conservation_passed": True,
                 "reference_checked": station_reference is not None,
                 "versions": {"python": platform.python_version(), "pandas": pd.__version__, "duckdb": duckdb.__version__, "pyarrow": pyarrow.__version__},
                 "elapsed_seconds": round(time.monotonic()-began, 3),
                 "definitions": {"hourly_cohort": "all valid nonnegative-duration records; missing target dates are null",
                    "main_replay": "0 < seconds <= 86400; both endpoints inside same continuous observed coverage span and requested range; cross-midnight retained",
                    "sensitivity": "departures/returns in exact table are all valid nonnegative records, including partial records on incomplete dates; filter coverage before evaluation",
                    "eligibility": "at target 00:00, any covered event in [target-28d,target), >=28 calendar days since first covered event; target observed",
                    "coverage": "departure-date presence proxy, not evidence of complete capture or station operation",
                    "split": "train 2023-01-01..2024-09-30; validation 2024-10-01..2024-12-31; test 2025-01-01..2025-06-30; July 2025 excluded"}}
        (stage / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        # Publication happens only after every conservation check passes.
        stage.rename(output_dir)
        return audit
    except Exception:
        # Preserve failure evidence in the staging directory; never publish partial output.
        (stage / "FAILED.txt").write_text("Pipeline failed; this directory is not a validated output.\n", encoding="utf-8")
        raise
    finally:
        if con is not None:
            con.close()


def build_panel(trip_paths: list[Path], start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """In-memory convenience interface; use the CLI for the full multi-year data."""
    with tempfile.TemporaryDirectory(prefix="nubija-event-panel-") as temp:
        out = Path(temp) / "panel"
        audit = run_pipeline(trip_paths, start, end, out)
        panel = pd.concat([pd.read_parquet(p) for p in sorted(out.glob("hourly_panel_*.parquet"))], ignore_index=True)
        masks = pd.read_parquet(out / "station_day_masks.parquet")
        panel.attrs["audit"] = audit
        return panel, masks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/event_panel")
    args = parser.parse_args()
    paths = [ROOT / f"data/raw/nubija_trips/nubija_trips_{y}.csv" for y in [2023, 2024, 2025]]
    result = run_pipeline(paths, args.start, args.end, args.output,
                          station_reference=ROOT / "data/raw/nubija_stations/nubija_stations_2023_2025.xlsx")
    print(json.dumps({k: result[k] for k in ["raw_rows", "clean_rows", "main_rows", "conservation_passed", "elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
