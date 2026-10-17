"""Daily-cutoff forecasts: actual future values never enter the model inputs."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/analysis/forecast_station_flows.py"
POLICY = ROOT / "scripts/analysis/compare_support_policies.py"
SIMULATOR = ROOT / "scripts/analysis/simulate_rebalancing.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


KASI = """{year}년  달 력 자 료
국경일과 공휴일
----------------------------------------------
    명칭             날짜           요일
----------------------------------------------
1월 1일                 1월  1일         일
설  날              2월 9일~ 2월11일  금,토,일
추  석              9월16일~ 9월18일  월,화,수
제헌절**                7월 17일         수
==============================================
*  국경일
"""


def activity_masks(panel, dates):
    """Masks as Task 1 defines them: activity in the prior 28 observed days."""
    daily = panel.assign(day=panel.event_time.dt.normalize()).groupby(["station_id", "day"])[["departures", "returns"]].sum().sum(axis=1)
    rows = []
    for station, series in daily.groupby(level=0):
        events = series.droplevel(0).reindex(dates, fill_value=0)
        prior = events.rolling(28, min_periods=1).sum().shift(1).fillna(0) > 0
        first = events[events > 0].index.min()
        for day in dates:
            established = first is not pd.NaT and (day - first).days >= 28
            rows.append(dict(station_id=station, target_date=day, forecast_cutoff=day, coverage_status="observed_departure_date",
                             observed_activity_prior_28d=bool(prior[day]), eligible_asof=bool(prior[day] and established),
                             history_complete_28=day >= dates[0] + pd.Timedelta(days=28),
                             history_stratum="established" if established else "new_under_28d"))
    return pd.DataFrame(rows)


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "forecast implementation is missing")
        self.api = _load(MODULE, "forecast_station_flows")

    def panel(self, start="2024-01-01", end="2024-02-01 23:00"):
        times = pd.date_range(start, end, freq="h")
        return pd.DataFrame({"station_id": "1", "event_time": times,
                             "departures": np.arange(len(times), dtype=float) % 17,
                             "returns": np.arange(len(times), dtype=float) % 13,
                             "coverage_status": "observed_departure_date",
                             "eligible_asof": True, "weather": 10.0})

    def weather(self, start="2022-12-01", end="2026-01-01 23:00"):
        hours = pd.date_range(start, end, freq="h")
        hourly = pd.DataFrame({"rain_mm": (np.arange(len(hours)) % 7 == 0) * 1.5,
                               "temp": 10 + np.sin(np.arange(len(hours)) / 24.0)}, index=hours)
        hourly.iloc[5::50, 0] = np.nan  # blank or QC-flag-9 hours stay missing
        days = pd.date_range(hours[0].normalize(), hours[-1].normalize())
        n = np.arange(len(days))
        daily = pd.DataFrame({"day_rain_mm": (n % 3) * 2.0, "day_temp_mean": 5 + n % 11 - 6.0,
                              "day_temp_max": 9 + n % 11 - 6.0, "day_wind_mean": 1 + (n % 5) * 0.4}, index=days)
        return hourly, daily

    def holidays(self, tmp, years=(2023, 2024, 2025)):
        paths = []
        for year in years:
            path = Path(tmp) / f"kasi_{year}.txt"
            path.write_text(KASI.format(year=year), encoding="utf-8")
            paths.append(path)
        return paths

    def test_cutoff_future_counts_weather_and_row_order_cannot_change_inputs(self):
        panel = self.panel()
        cutoff = pd.Timestamp("2024-01-30")
        before = self.api.make_features(panel, cutoff)
        changed = panel.copy()
        changed.loc[changed.event_time.ge(cutoff), ["departures", "returns", "weather"]] = 100000
        after = self.api.make_features(changed.sample(frac=1, random_state=42), cutoff)
        pd.testing.assert_frame_equal(before, after)
        self.assertEqual(len(before), 24)
        self.assertNotIn("weather", before)
        self.assertNotIn("departures", before)
        target = before.iloc[9]
        past = panel.set_index("event_time")
        t = target.event_time
        self.assertEqual(target.departures_lag_24, past.loc[t-pd.Timedelta(hours=24), "departures"])
        self.assertEqual(target.departures_mean_28, np.mean([
            past.loc[t-pd.Timedelta(days=d), "departures"] for d in [7, 14, 21, 28]]))

    def test_context_past_inputs_ignore_weather_at_or_after_cutoff_but_oracle_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            holidays = self.api.kasi_holidays(self.holidays(tmp))
        hourly, daily = self.weather()
        cutoff = pd.Timestamp("2024-03-05")
        past_cols = self.api.CALENDAR_FEATURES + self.api.WEATHER_PAST
        oracle_cols = self.api.WEATHER_ORACLE_DAY + self.api.WEATHER_ORACLE_HOUR
        d0, h0 = self.api.context_tables(holidays, hourly, daily, "2024-02-01", "2024-03-10")
        hourly2, daily2 = hourly.copy(), daily.copy()
        hourly2.loc[hourly2.index >= cutoff, :] = 999.0
        daily2.loc[daily2.index >= cutoff, :] = 999.0
        d1, h1 = self.api.context_tables(holidays, hourly2, daily2, "2024-02-01", "2024-03-10")
        day = slice(cutoff, cutoff + pd.Timedelta(hours=23))
        pd.testing.assert_frame_equal(h0.loc[day, past_cols], h1.loc[day, past_cols])
        pd.testing.assert_series_equal(d0.loc[cutoff, past_cols], d1.loc[cutoff, past_cols])
        self.assertTrue((h1.loc[day, oracle_cols] == 999.0).all().all())
        self.assertFalse(h0.loc[day, oracle_cols].eq(999.0).any().any())
        # ... and the past inputs really are the previous day's observations
        daily3 = daily.copy()
        daily3.loc[cutoff - pd.Timedelta(days=1), "day_wind_mean"] = 77.0
        d3, _ = self.api.context_tables(holidays, hourly, daily3, "2024-02-01", "2024-03-10")
        self.assertEqual(d3.loc[cutoff, "wx_prev_day_wind_mean"], 77.0)
        self.assertEqual(d0.loc[cutoff, "wx_prev_day_rain_mm"], daily.loc[cutoff - pd.Timedelta(days=1), "day_rain_mm"])
        # rain of event hour t is the observation at tm=t+1h (accumulated over [t, t+1h))
        self.assertEqual(h0.loc[cutoff + pd.Timedelta(hours=8), "wx_hour_temp"], hourly.loc[cutoff + pd.Timedelta(hours=9), "temp"])
        with self.assertRaises(ValueError):
            self.api.context_tables(holidays, hourly, daily, "2022-12-20", "2023-01-10")

    def test_feature_availability_oracle_isolated_and_never_selectable(self):
        api = self.api
        for name, features in list(api.HOURLY_MODELS.items()) + list(api.DAILY_MODELS.items()):
            if not features:
                continue
            has_oracle = any(api.AVAILABILITY[f] == "oracle_observed_after_cutoff" for f in features)
            self.assertEqual(has_oracle, name in api.ORACLE_MODELS, name)
            self.assertTrue(all(f in api.AVAILABILITY for f in features))
        self.assertFalse(set(api.HOURLY_SELECTION_ORDER + api.Q_AI_ORDER) & api.ORACLE_MODELS)
        with self.assertRaises(ValueError):
            api.select_model({"baseline": 2., "gb_oracle_weather": 1.})
        with self.assertRaises(ValueError):
            api.select_model({"qgb_lags": 2., "qgb_oracle_weather": 1.}, api.Q_AI_ORDER)
        self.assertEqual(api.select_model({"baseline": 2., "baseline_lastweek": 1., "gb_calendar": 1.}), "baseline_lastweek")
        self.assertEqual(api.select_model({"qgb_lags": 1., "qgb_calendar": 1.}, api.Q_AI_ORDER), "qgb_lags")
        splits = {k: tuple(pd.Timestamp(v) for v in vs) for k, vs in api.SPLITS.items()}
        self.assertLess(splits["train"][1], splits["validation"][0])
        self.assertLess(splits["validation"][1], splits["test"][0])
        self.assertLess(splits["test"][1], pd.Timestamp("2025-07-01"))

    def test_kasi_calendar_holidays_supplement_and_seollal_chuseok_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            holidays = self.api.kasi_holidays(self.holidays(tmp))
        self.assertEqual(holidays.attrs["covered_years"], [2023, 2024, 2025])
        self.assertIn(pd.Timestamp("2024-02-10"), holidays.index)
        self.assertNotIn(pd.Timestamp("2024-07-17"), holidays.index)  # '**' national day, not a holiday
        self.assertIn(pd.Timestamp("2025-06-03"), holidays.index)     # supplement: election day
        self.assertIn(pd.Timestamp("2024-10-01"), holidays.index)     # supplement: temporary holiday
        calendar = self.api.calendar_table(holidays)
        self.assertEqual(calendar.loc["2024-09-16", "cal_major_holiday"], 1)  # '추  석' spacing
        self.assertEqual(calendar.loc["2024-09-14", "cal_major_holiday"], 1)  # weekend joined to the block
        self.assertEqual(calendar.loc["2024-09-12", "cal_major_holiday"], 2)
        self.assertEqual(calendar.loc["2024-09-20", "cal_major_holiday"], 3)
        self.assertEqual(calendar.loc["2024-10-01", "cal_holiday"], 1)
        self.assertEqual(calendar.loc["2024-10-02", "cal_prev_offday"], 1)
        self.assertEqual(calendar.loc["2024-10-08", "cal_lag7_offday"], 1)
        real = [ROOT / f"data/raw/calendar/kasi_calendarData_{y}.txt" for y in [2023, 2024, 2025]]
        if all(p.exists() for p in real):  # the parent's checked list: 18 / 19 / 19 public-office holidays
            names = self.api.kasi_holidays(real)
            self.assertEqual([int((names.index.year == y).sum()) for y in [2023, 2024, 2025]], [18, 19, 19])
            self.assertEqual(self.api.calendar_table(names).loc["2025-01-25":"2025-01-30", "cal_major_holiday"].tolist(), [1.0] * 6)

    def test_weather_blank_hourly_rain_stays_missing_and_blank_daily_rain_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pd.DataFrame({"tm": ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 02:00"], "ta": [1.0, None, -3.5],
                          "rn": [None, None, 2.5], "rnQcflg": [None, 9, None]}).to_csv(base / "h.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame({"tm": ["2024-01-01", "2024-01-02"], "sumRn": [None, 4.0], "avgTa": [1.0, 2.0],
                          "maxTa": [None, 5.0], "avgWs": [1.2, 2.0]}).to_csv(base / "d.csv", index=False, encoding="utf-8-sig")
            hourly, daily = self.api.weather_tables(base / "h.csv", [base / "d.csv"])
        self.assertTrue(np.isnan(hourly.rain_mm.iloc[0]))   # blank hourly rain: unknown (3-hourly in winter), not 0
        self.assertTrue(np.isnan(hourly.rain_mm.iloc[1]))   # QC flag 9: missing
        self.assertEqual(hourly.rain_mm.iloc[2], 2.5)
        self.assertTrue(np.isnan(hourly.temp.iloc[1]))
        self.assertEqual(hourly.temp.iloc[2], -3.5)
        self.assertEqual(daily.day_rain_mm.tolist(), [0.0, 4.0])  # blank daily sumRn: no-rain day (iscs cross-check)
        self.assertTrue(np.isnan(daily.day_temp_max.iloc[0]))

    def test_curve_q_is_the_simulator_q_and_exact_q_from_timestamps(self):
        simulator, policy = _load(SIMULATOR, "simulate_rebalancing"), _load(POLICY, "compare_support_policies")
        rng = np.random.default_rng(3)
        d, r = rng.poisson(2.0, (50, 22)).astype(float) * 0.7, rng.poisson(2.0, (50, 22)).astype(float) * 0.9
        np.testing.assert_array_equal(self.api.curve_q(d, r), simulator.q_from_hourly(d, r))
        np.testing.assert_allclose(self.api.curve_q(d, r), [policy.required_start_buffer(d[i], r[i]) for i in range(50)], atol=1e-9)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            events = pd.DataFrame({"station_id": ["1", "1", "1", "1", "2"],
                                   "event_time": pd.to_datetime(["2024-01-02 08:00", "2024-01-03 07:00", "2024-01-03 08:00",
                                                                 "2024-01-03 09:00", "2024-01-02 23:59"]),
                                   "departures": [1, 0, 3, 0, 0], "returns": [1, 2, 0, 0, 1],
                                   "main_departures": [1, 0, 3, 0, 0], "main_returns": [1, 2, 0, 0, 1],
                                   "coverage_status": "observed_departure_date"})
            events.to_parquet(base / "events.parquet", index=False)
            dates = pd.date_range("2024-01-01", "2024-01-04")
            masks = pd.DataFrame([(s, d) for s in ["1", "2"] for d in dates], columns=["station_id", "target_date"])
            masks["coverage_status"] = np.where(masks.target_date.eq(pd.Timestamp("2024-01-04")), "unobserved_date", "observed_departure_date")
            masks.to_parquet(base / "masks.parquet", index=False)
            q = self.api.observed_daily_q([base / "events.parquet"], base / "masks.parquet", "2024-01-01", "2024-01-04")
        got = q.set_index(["station_id", q.target_date.dt.strftime("%m-%d")]).q.to_dict()
        self.assertEqual(got[("1", "01-02")], 1)   # same-timestamp departure counted before the return
        self.assertEqual(got[("1", "01-03")], 1)   # 2 returns at 07:00, then 3 departures at 08:00
        self.assertEqual(got[("1", "01-01")], 0)   # observed day without events
        self.assertEqual(got[("2", "01-02")], 0)
        self.assertNotIn(("1", "01-04"), got)      # unobserved day is absent, not zero

    def test_station_day_table_is_simulator_q_from_past_days_only(self):
        simulator = _load(SIMULATOR, "simulate_rebalancing")
        rng = np.random.default_rng(7)
        times = pd.date_range("2024-01-01", "2024-03-10 23:00", freq="h")
        frames = []
        for station, opened in [("1", "2024-01-01"), ("2", "2024-02-20")]:
            on = times >= pd.Timestamp(opened)
            frames.append(pd.DataFrame({"station_id": station, "event_time": times,
                                        "departures": np.where(on, rng.poisson(1.5, len(times)), 0).astype("int32"),
                                        "returns": np.where(on, rng.poisson(1.4, len(times)), 0).astype("int32"),
                                        "coverage_status": "observed_departure_date", "eligible_asof": True}))
        panel = pd.concat(frames, ignore_index=True)
        dates = pd.date_range("2024-01-01", "2024-03-10")
        masks = activity_masks(panel, dates)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            masks.to_parquet(base / "masks.parquet", index=False)
            daily_ctx, _ = self.api.context_tables(self.api.kasi_holidays(self.holidays(tmp)), *self.weather(), "2024-01-01", "2024-03-10")
            tables = {}
            for label, frame in [("original", panel), ("future_changed", panel.assign(
                    departures=np.where(panel.event_time >= pd.Timestamp("2024-03-05"), 40, panel.departures)))]:
                frame.to_parquet(base / f"{label}.parquet", index=False)
                cube = self.api.hourly_cube([base / f"{label}.parquet"], "2024-01-01", "2024-03-10")
                tables[label] = self.api.daily_table(cube, base / "masks.parquet", daily_ctx, "2024-02-15", "2024-03-10")
            unobserved = panel.assign(coverage_status=np.where(panel.event_time.dt.normalize().eq(pd.Timestamp("2024-02-01")),
                                                               "unobserved_date", "observed_departure_date"))
            unobserved.to_parquet(base / "gap.parquet", index=False)
            gap = self.api.hourly_cube([base / "gap.parquet"], "2024-01-01", "2024-03-10")
            with self.assertRaises(ValueError):  # a 28-day window with an unobserved date is refused, not zero-filled
                self.api.daily_table(gap, base / "masks.parquet", daily_ctx, "2024-02-15", "2024-03-10")
            self.assertLess(len(self.api.daily_table(gap, base / "masks.parquet", daily_ctx, "2024-02-15", "2024-03-10", strict=False)),
                            len(tables["original"]))
        table = tables["original"]
        expected_rows = masks[masks.observed_activity_prior_28d & masks.target_date.between("2024-02-15", "2024-03-10")]
        self.assertEqual(len(table), len(expected_rows))
        hourly = panel.assign(day=panel.event_time.dt.normalize(), hour=panel.event_time.dt.hour)

        def curves(station, days):
            part = hourly[hourly.station_id.eq(station) & hourly.day.isin(days)]
            dep = part.pivot_table(index="day", columns="hour", values="departures").reindex(days).to_numpy(float)
            ret = part.pivot_table(index="day", columns="hour", values="returns").reindex(days).to_numpy(float)
            return dep, ret

        target = pd.Timestamp("2024-03-05")
        row = table[table.station_id.eq("1") & table.target_date.eq(target)].iloc[0]
        dep, ret = curves("1", [target])
        self.assertEqual(row.q_actual, simulator.q_from_hourly(dep[:, 2:], ret[:, 2:])[0])
        dep, ret = curves("1", [target - pd.Timedelta(days=7)])
        self.assertEqual(row.q_lag_7, simulator.q_from_hourly(dep[:, 2:], ret[:, 2:])[0])
        dep, ret = curves("1", [target - pd.Timedelta(days=k) for k in [7, 14, 21, 28]])
        self.assertAlmostEqual(row.q_rule4w, simulator.q_from_hourly(dep.mean(axis=0)[None, 2:], ret.mean(axis=0)[None, 2:])[0], places=12)
        changed = tables["future_changed"].set_index(["station_id", "target_date"]).loc[("1", target)]
        for column in self.api.DAILY_BASE + self.api.CALENDAR_FEATURES + self.api.WEATHER_PAST:
            self.assertEqual(changed[column], row[column], column)
        self.assertNotEqual(changed.q_actual, row.q_actual)
        new = table[table.station_id.eq("2")].sort_values("target_date")
        self.assertTrue(new.station_age_group.eq("new_under_28d").all() and not new.in_hourly_universe.any())
        first_day = new.iloc[0]
        self.assertEqual(first_day.target_date, pd.Timestamp("2024-02-21"))
        dep, ret = curves("2", [pd.Timestamp("2024-02-20")])
        self.assertEqual(first_day.q_station_mean, simulator.q_from_hourly(dep[:, 2:], ret[:, 2:])[0])
        self.assertEqual(first_day.station_age_capped, 1)
        self.assertEqual(first_day.q_lag_7, 0.0)  # observed day before opening: zero events, not missing

    def test_forecast_metrics_within_two_under_rate_and_city_error(self):
        frame = pd.DataFrame({"model": "m", "station_id": ["1", "2"], "target_date": pd.to_datetime(["2024-10-01"] * 2),
                              "pred_departures_day": [10.4, 7.6], "departures_day": [8.0, 11.0],
                              "pred_returns_day": [1.0, 1.0], "returns_day": [1.0, 3.0],
                              "pred_netflow_day": [9.4, 6.6], "netflow_day": [7.0, 8.0],
                              "q_raw": [2.2, 0.5], "q_actual": [3.0, 3.0], "q_exact": [2.0, 3.0],
                              "district": "성산구", "activity_stratum": "a", "day_type": "weekday",
                              "rain_day": "dry_under_1mm", "major_holiday_window": "none"})
        m = self.api.forecast_metrics(frame, "validation", self.api.E_DIMENSIONS).query("dimension == 'overall'").iloc[0]
        self.assertAlmostEqual(m.departures_day_within2, 0.5)  # round(10.4)=10 vs 8 hit; round(7.6)=8 vs 11 miss
        self.assertAlmostEqual(m.q_mae, 1.65)
        self.assertAlmostEqual(m.q_within2, 0.5)
        self.assertAlmostEqual(m.q_under_rate, 1.0)
        self.assertAlmostEqual(m.q_under_units, 1.65)
        self.assertAlmostEqual(m.q_bias, -1.65)
        self.assertAlmostEqual(m.qx_mae, 1.35)
        self.assertAlmostEqual(m.departures_day_wape, (2.4 + 3.4) / 2 / 9.5)
        city, summary = self.api.city_metrics(frame, "validation")
        self.assertAlmostEqual(city.departures_pct_error.iloc[0], (18.0 - 19.0) / 19.0 * 100)
        self.assertAlmostEqual(summary.query("dimension == 'overall'").city_departures_mape.iloc[0], 100 / 19.0)

    def test_incomplete_warmup_ineligible_and_july_are_excluded_not_zero_filled(self):
        panel = self.panel()
        self.assertTrue(self.api.make_features(panel, pd.Timestamp("2024-01-20")).empty)
        panel.loc[panel.event_time.eq(pd.Timestamp("2024-01-05 04:00")), "departures"] = np.nan
        self.assertTrue(self.api.make_features(panel, pd.Timestamp("2024-01-30")).empty)
        panel = self.panel()
        panel.loc[panel.event_time.ge(pd.Timestamp("2024-01-30")), "eligible_asof"] = False
        self.assertTrue(self.api.make_features(panel, pd.Timestamp("2024-01-30")).empty)
        july = self.panel("2025-06-01", "2025-08-31 23:00")
        self.assertTrue(self.api.make_features(july, pd.Timestamp("2025-07-01")).empty)
        july.loc[july.event_time.dt.month.eq(7), ["departures", "returns"]] = np.nan
        july.loc[july.event_time.dt.month.eq(7), "coverage_status"] = "incomplete_missing_july"
        self.assertTrue(self.api.make_features(july, pd.Timestamp("2025-08-10")).empty)
        self.assertEqual(len(self.api.make_features(july, pd.Timestamp("2025-08-29"))), 24)
        with self.assertRaises(ValueError):
            self.api.make_features(panel, pd.Timestamp("2024-01-30 01:00"))

    def test_baseline_and_poisson_nonnegative_keys_and_training_split(self):
        panel = self.panel()
        features = self.api.make_features(panel, pd.Timestamp("2024-01-30"))
        train = features.copy()
        train["departures"] = np.arange(24, dtype=float) % 5
        train["returns"] = np.arange(24, dtype=float) % 3
        for column in self.api.CONTEXT_HOURLY:
            value = np.where(np.arange(24) % 4 == 0, np.nan, -1.5) if column.startswith("wx_") else np.arange(24) % 2
            train[column] = features[column] = value
        for model in self.api.HOURLY_MODELS:
            predicted = self.api.fit_predict(train, features, model)
            self.assertEqual(list(predicted), ["station_id", "event_time", "cutoff", "model", "pred_departures", "pred_returns"])
            self.assertTrue(np.isfinite(predicted[["pred_departures", "pred_returns"]]).all().all())
            self.assertTrue(predicted[["pred_departures", "pred_returns"]].ge(0).all().all())
        baseline = self.api.fit_predict(train, features, "baseline")
        np.testing.assert_array_equal(baseline.pred_returns, features.returns_mean_28)
        lastweek = self.api.fit_predict(train, features, "baseline_lastweek")
        np.testing.assert_array_equal(lastweek.pred_departures, features.departures_lag_168)
        train["departures"] = 0.0
        zeros = self.api.fit_predict(train, features, "hist_gb_poisson")
        self.assertTrue(zeros.pred_departures.eq(0).all())
        train["departures"] = -1.0
        with self.assertRaises(ValueError):
            self.api.fit_predict(train, features, "hist_gb_poisson")
        train["departures"] = 1.0
        train["cal_holiday"] = np.nan  # calendar inputs may never be missing
        with self.assertRaises(ValueError):
            self.api.fit_predict(train, features, "gb_calendar")

    def test_metrics_signed_netflow_zero_denominator_and_selection_tie(self):
        actual = pd.DataFrame({"departures": [0, 2], "returns": [0, 2],
                               "pred_departures": [1, 1], "pred_returns": [0, 2]})
        result = self.api.flow_metrics(actual)
        self.assertEqual(result["departures_mae"], 1)
        self.assertEqual(result["departures_wape"], 1)
        self.assertEqual(result["netflow_mae"], 1)
        self.assertTrue(np.isnan(result["netflow_wape"]))
        self.assertEqual(self.api.select_model({"baseline": 2., "hist_gb_poisson": 2.}), "baseline")
        self.assertEqual(self.api.select_model({"baseline": 2., "hist_gb_poisson": 1.9}), "hist_gb_poisson")
        with self.assertRaises(ValueError):
            self.api.select_model({"baseline": 2., "hist_gb_poisson": np.nan})

    def test_parquet_features_match_cutoff_api_and_both_masks(self):
        panel = self.panel().drop(columns="weather")
        dates = panel.event_time.dt.normalize().drop_duplicates()
        masks = pd.DataFrame({"station_id": "1", "target_date": dates, "forecast_cutoff": dates,
                              "eligible_asof": True, "history_complete_28": dates.ge(pd.Timestamp("2024-01-29")),
                              "history_stratum": "established"})
        masks.loc[masks.target_date.eq(pd.Timestamp("2024-01-31")), "history_complete_28"] = False
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            panel.to_parquet(base / "hourly.parquet", index=False)
            masks.to_parquet(base / "masks.parquet", index=False)
            self.api.build_feature_parquet([base / "hourly.parquet"], base / "masks.parquet",
                                           base / "features.parquet", "2024-01-30", "2024-01-31")
            actual = pd.read_parquet(base / "features.parquet").sort_values("event_time").reset_index(drop=True)
            expected = self.api.make_features(panel, pd.Timestamp("2024-01-30"))
            self.assertEqual(len(actual), 24)
            pd.testing.assert_frame_equal(actual[list(expected)], expected, check_dtype=False)

    def test_historical_district_map_does_not_backfill_future_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stations.xlsx"
            with pd.ExcelWriter(path) as writer:
                pd.DataFrame({"터미널번호": ["1"], "구": ["성산구"]}).to_excel(writer, sheet_name="2023년", index=False)
                pd.DataFrame({"터미널번호": ["1", "2"], "구": ["성산구", "진해구"]}).to_excel(writer, sheet_name="2024년", index=False)
            mapping = self.api.district_reference(path)
            self.assertEqual(mapping.query("year == 2023").station_id.tolist(), ["1"])
            self.assertEqual(mapping.query("year == 2024 and station_id == '2'").district.iloc[0], "진해구")

    def test_parquet_activity_and_completeness_are_frozen_at_midnight(self):
        panel = self.panel().drop(columns="weather")
        panel[["departures", "returns"]] = 0.0
        panel.loc[panel.event_time.eq(pd.Timestamp("2024-01-29 23:00")), "departures"] = 1.0
        cutoff = pd.Timestamp("2024-01-30")
        masks = pd.DataFrame({"station_id": ["1"], "target_date": [cutoff], "forecast_cutoff": [cutoff],
                              "eligible_asof": [True], "history_complete_28": [True], "history_stratum": ["established"]})
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            masks.to_parquet(base / "masks.parquet", index=False)
            for label, changed in [("before", panel.copy()), ("after", panel.copy())]:
                if label == "after":
                    changed.loc[changed.event_time.ge(cutoff), ["departures", "returns"]] = 1000.
                changed.to_parquet(base / "panel.parquet", index=False)
                self.api.build_feature_parquet([base / "panel.parquet"], base / "masks.parquet",
                                               base / f"{label}.parquet", "2024-01-30", "2024-01-30")
            before, after = [pd.read_parquet(base / f"{label}.parquet") for label in ["before", "after"]]
            feature_cols = self.api.KEYS + self.api.FEATURES + ["activity_stratum"]
            pd.testing.assert_frame_equal(before[feature_cols], after[feature_cols])
            self.assertTrue(after.activity_stratum.eq("low_under_1_event_daily").all())

    def test_existing_stage_refused_and_publish_archives_previous_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stage = base / "stage"
            stage.mkdir()
            (stage / "keep.txt").write_text("prior stage")
            with self.assertRaises(FileExistsError):
                self.api.run_validation_phase(self.api.default_inputs(base), stage)
            self.assertEqual((stage / "keep.txt").read_text(), "prior stage")
            output = base / "forecast"
            output.mkdir()
            (output / "metrics.csv").write_text("verified prior result")
            new = base / "metrics.csv"
            new.write_text("new result")
            archived = self.api._publish([new], output, "_archive_x")
            self.assertEqual((output / "_archive_x" / "metrics.csv").read_text(), "verified prior result")
            self.assertEqual((output / "metrics.csv").read_text(), "new result")
            self.assertIn("metrics.csv", archived)
            with self.assertRaises(FileExistsError):
                self.api._publish([new], output, "_archive_x")

    def test_two_phase_protocol_locks_before_test_and_opens_test_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            panels, raw = base / "panel", base / "raw"
            panels.mkdir()
            raw.mkdir()
            panel = self.panel("2023-01-01", "2025-06-30 23:00").drop(columns="weather")
            dates = panel.event_time.dt.normalize().drop_duplicates()
            masks = pd.DataFrame({"station_id": "1", "target_date": dates, "forecast_cutoff": dates,
                                  "coverage_status": "observed_departure_date",
                                  "observed_activity_prior_28d": dates.ge(pd.Timestamp("2023-01-02")),
                                  "eligible_asof": dates.ge(pd.Timestamp("2023-01-29")),
                                  "history_complete_28": dates.ge(pd.Timestamp("2023-01-29")),
                                  "history_stratum": "established"})
            masks.to_parquet(panels / "station_day_masks.parquet", index=False)
            events = panel.assign(main_departures=panel.departures.astype(int), main_returns=panel.returns.astype(int),
                                  departures=panel.departures.astype(int), returns=panel.returns.astype(int))
            hourly, daily = self.weather("2023-01-01", "2025-12-31 23:00")
            pd.DataFrame({"tm": hourly.index.strftime("%Y-%m-%d %H:%M"), "ta": hourly.temp,
                          "rn": hourly.rain_mm.where(hourly.rain_mm > 0), "rnQcflg": np.where(hourly.rain_mm.isna(), 9, np.nan)}
                         ).to_csv(raw / "asos_hourly.csv", index=False, encoding="utf-8-sig")
            for year in [2023, 2024, 2025]:
                part = daily[daily.index.year == year]
                pd.DataFrame({"tm": part.index.strftime("%Y-%m-%d"), "sumRn": part.day_rain_mm.where(part.day_rain_mm > 0),
                              "avgTa": part.day_temp_mean, "maxTa": part.day_temp_max, "avgWs": part.day_wind_mean}
                             ).to_csv(raw / f"asos_daily_{year}.csv", index=False, encoding="utf-8-sig")
            workbook = base / "stations.xlsx"
            with pd.ExcelWriter(workbook) as writer:
                for year in [2023, 2024, 2025]:
                    pd.DataFrame({"터미널번호": ["1"], "구": ["성산구"]}).to_excel(writer, sheet_name=f"{year}년", index=False)
            inputs = {"panel": [panels / f"hourly_panel_{y}.parquet" for y in [2023, 2024, 2025]],
                      "events": [panels / f"exact_events_{y}.parquet" for y in [2023, 2024, 2025]],
                      "masks": panels / "station_day_masks.parquet", "stations": workbook,
                      "calendar": self.holidays(raw), "weather_hourly": raw / "asos_hourly.csv",
                      "weather_daily": [raw / f"asos_daily_{y}.csv" for y in [2023, 2024, 2025]],
                      "task4_validation_q": None}
            for year in [2023, 2024]:  # 2025 bike files are absent during the validation phase
                panel[panel.event_time.dt.year.eq(year)].to_parquet(inputs["panel"][year - 2023], index=False)
                events[events.event_time.dt.year.eq(year)].to_parquet(inputs["events"][year - 2023], index=False)
            stage = base / "stage"
            audit = self.api.run_validation_phase(inputs, stage)
            lock = json.loads((stage / "model_selection.json").read_text(encoding="utf-8"))
            self.assertFalse(lock["test_scores_viewed"])
            self.assertNotIn(lock["chosen_model"], self.api.ORACLE_MODELS)
            self.assertIn(lock["q_ai_model"], self.api.Q_AI_ORDER)
            self.assertEqual(set(lock["test_inputs_sha256"].values()), {None})
            self.assertEqual((stage / "model_selection.sha256").read_text().strip(), audit["selection_sha256"])
            self.assertEqual(audit["model_iterations"]["hist_gb_poisson"], {"departures": 100, "returns": 100})
            self.assertFalse(list(stage.glob("*test*")))
            panel[panel.event_time.dt.year.eq(2025)].to_parquet(inputs["panel"][2], index=False)
            events[events.event_time.dt.year.eq(2025)].to_parquet(inputs["events"][2], index=False)
            original = (stage / "model_selection.json").read_bytes()
            (stage / "model_selection.json").write_bytes(original.replace(b'"test_scores_viewed": false', b'"test_scores_viewed": true '))
            with self.assertRaises(ValueError):
                self.api.run_test_phase(inputs, stage, base / "forecast")
            (stage / "model_selection.json").write_bytes(original)
            output = base / "forecast"
            output.mkdir()
            (output / "metrics.csv").write_text("v1")
            audit = self.api.run_test_phase(inputs, stage, output)
            self.assertTrue(audit["headline_allowed"])
            self.assertEqual(audit["test_refits"], 0)
            self.assertEqual((output / "_archive_20261017" / "metrics.csv").read_text(), "v1")
            completeness = pd.read_csv(output / "prediction_completeness.csv")
            self.assertTrue(completeness.missing_predictions.eq(0).all())
            self.assertTrue(completeness.query("split == 'test' and unit == 'hourly'").days.eq(181).all())
            for split, days in [("validation", 92), ("test", 181)]:
                for name, model in [(f"selected_predictions_{split}", lock["chosen_model"]),
                                    (f"predictions_{split}_oracle_weather", "gb_oracle_weather"),
                                    (f"predictions_{split}_baseline4w", "baseline")]:
                    frame = pd.read_parquet(output / f"{name}.parquet")
                    self.assertEqual(list(frame), self.api.PRED_COLUMNS)
                    self.assertEqual(len(frame), days * 24)
                    self.assertEqual(set(frame.model), {model})
                    low, high = (pd.Timestamp(v) for v in self.api.SPLITS[split])
                    self.assertTrue(pd.to_datetime(frame.cutoff).between(low, high).all())
                q = pd.read_parquet(output / f"q_pred_{split}.parquet")
                self.assertEqual(list(q)[:6], ["station_id", "day", "q_rule4w", "q_ai", "q_ai_oracle_weather", "q_actual"])
                self.assertEqual(len(q), days)
                self.assertFalse(q.isna().any().any())
                self.assertEqual(str(q.station_id.dtype), "int64")
                self.assertEqual(type(q.day.iloc[0]).__name__, "date")
            summary = pd.read_csv(output / "improvement_summary.csv")
            self.assertEqual(set(summary.split), {"validation", "test"})
            self.assertIn("규칙R", (output / "summary_tables.md").read_text(encoding="utf-8"))
            self.assertFalse((output / "scratch").exists())
            with self.assertRaises(ValueError):  # one opening per lock
                self.api.run_test_phase(inputs, stage, base / "forecast2")


if __name__ == "__main__":
    unittest.main()
