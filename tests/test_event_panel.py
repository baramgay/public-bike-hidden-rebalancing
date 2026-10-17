"""Temporal boundaries, missingness and as-of activity masks on small real CSVs."""
from pathlib import Path
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/analysis/build_event_panel.py"
COLUMNS = ["자전거번호", "출발터미널", "출발일", "출발시간", "도착터미널", "도착일", "도착시간"]


class EventPanelTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "event-panel implementation is missing")
        spec = importlib.util.spec_from_file_location("build_event_panel", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def source(self, year, rows):
        path = self.base / f"trips_{year}.csv"
        pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, encoding="cp949")
        return path

    def row(self, start, end, origin="1", destination="2", bike="PRIVATE_BIKE"):
        d, t = start.split(" ")
        e, u = end.split(" ")
        return [bike, origin, d, t, destination, e, u]

    def test_real_event_dates_include_previous_file_spillovers_once(self):
        paths = [
            self.source(2023, [self.row("2023-12-31 23:55:00", "2024-01-01 00:05:00")]),
            self.source(2024, [self.row("2024-12-31 23:55:00", "2025-01-01 00:05:00")]),
            self.source(2025, [self.row("2025-01-01 08:00:00", "2025-01-01 08:10:00")]),
        ]
        panel, masks = self.api.build_panel(paths, "2024-01-01", "2025-01-01")
        self.assertEqual(panel["departures"].sum(), 2)
        self.assertEqual(panel["returns"].sum(), 2)  # Jan 2024 arrival is retained but masked, not silently zero.
        jan24 = panel[(panel.station_id == "2") & (panel.event_time == pd.Timestamp("2024-01-01"))]
        self.assertTrue(jan24.returns.isna().all())
        jan25 = panel[(panel.station_id == "2") & (panel.event_time == pd.Timestamp("2025-01-01"))]
        self.assertEqual(jan25.returns.iloc[0], 1)
        audit = panel.attrs["audit"]
        self.assertEqual(audit["all_valid_events_in_range"]["returns"], 3)

    def test_missing_july_and_arrival_only_days_are_nan_not_zero(self):
        path = self.source(2025, [
            self.row("2025-06-30 23:50:00", "2025-07-01 00:10:00"),
            self.row("2025-07-10 09:00:00", "2025-07-10 09:05:00"),
            self.row("2025-08-01 09:00:00", "2025-08-01 09:05:00"),
        ])
        panel, masks = self.api.build_panel([path], "2025-06-30", "2025-08-02")
        july = panel[panel.event_time.dt.month.eq(7)]
        self.assertTrue(july[["departures", "returns"]].isna().all().all())
        self.assertEqual(set(july.coverage_status), {"incomplete_missing_july"})
        aug2 = panel[panel.event_time.dt.day.eq(2) & panel.event_time.dt.month.eq(8)]
        self.assertTrue(aug2.departures.isna().all())
        aug1 = panel[(panel.event_time == pd.Timestamp("2025-08-01")) & panel.station_id.eq("1")]
        self.assertEqual(aug1.departures.iloc[0], 0)
        self.assertFalse(masks[masks.target_date.dt.month.eq(7)].eligible_asof.any())

    def test_eligibility_cutoff_excludes_target_day_and_future_activity(self):
        rows = [self.row("2024-01-01 08:00:00", "2024-01-01 08:10:00", "1", "1"),
                self.row("2024-01-28 08:00:00", "2024-01-28 08:10:00", "1", "1"),
                self.row("2024-01-29 08:00:00", "2024-01-29 08:10:00", "NEW", "NEW"),
                self.row("2024-03-01 08:00:00", "2024-03-01 08:10:00", "FUTURE", "FUTURE")]
        panel, masks = self.api.build_panel([self.source(2024, rows)], "2024-01-01", "2024-03-01")
        day = masks[masks.target_date.eq(pd.Timestamp("2024-01-29"))].set_index("station_id")
        self.assertTrue(day.loc["1", "eligible_asof"])
        self.assertFalse(day.loc["NEW", "eligible_asof"])
        self.assertFalse(day.loc["FUTURE", "eligible_asof"])
        self.assertEqual(day.loc["1", "forecast_cutoff"], pd.Timestamp("2024-01-29"))
        jan2 = masks[(masks.target_date == pd.Timestamp("2024-01-02")) & masks.station_id.eq("1")]
        self.assertEqual(jan2.history_stratum.iloc[0], "new_under_28d")

    def test_exact_ties_zero_long_unknown_ids_and_conservation(self):
        rows = [
            self.row("2024-01-01 08:00:00", "2024-01-01 08:10:00"),
            self.row("2024-01-01 08:10:00", "2024-01-01 08:20:00", "2", "1"),
            self.row("2024-01-01 09:00:00", "2024-01-01 09:00:00", "1", "1"),
            self.row("2024-01-01 10:00:00", "2024-01-03 11:00:00", "1", "999"),
            self.row("2024-01-01 23:55:00", "2024-01-02 00:05:00"),
            self.row("2024-01-02 10:00:00", "2024-01-02 10:10:00"),
            self.row("2024-01-01 12:00:00", "2024-01-01 11:00:00"),
        ]
        ref = self.base / "stations.xlsx"
        with pd.ExcelWriter(ref) as writer:
            pd.DataFrame({"터미널번호": ["1", "2"]}).to_excel(writer, sheet_name="2024년", index=False)
        out = self.base / "output"
        audit = self.api.run_pipeline([self.source(2024, rows)], "2024-01-01", "2024-01-03", out,
                                      station_reference=ref, chunksize=2)
        exact = pd.read_parquet(out / "exact_events_2024.parquet")
        tie = exact[exact.station_id.eq("2") & exact.event_time.eq(pd.Timestamp("2024-01-01 08:10:00"))].iloc[0]
        self.assertEqual((tie.departures, tie.returns), (1, 1))
        self.assertEqual((exact.departures.sum(), exact.returns.sum()), (6, 6))
        self.assertEqual((exact.main_departures.sum(), exact.main_returns.sum()), (4, 4))
        self.assertEqual(audit["raw_rows"], 7)
        self.assertEqual(audit["clean_rows"], 6)
        self.assertEqual(audit["anomalies"]["negative_duration"], 1)
        self.assertEqual(audit["anomalies"]["zero_seconds"], 1)
        self.assertEqual(audit["anomalies"]["over_24h"], 1)
        unknown = pd.read_csv(out / "unmatched_station_ids.csv", dtype={"station_id": str})
        self.assertEqual(set(unknown.station_id), {"999"})
        self.assertEqual(unknown.events.sum(), 1)
        self.assertFalse(any("PRIVATE_BIKE" in p.read_text(errors="ignore") for p in out.glob("*.csv")))
        self.assertNotIn("자전거번호", exact.columns)
        self.assertTrue(audit["conservation_passed"])

    def test_full_24h_cross_midnight_is_kept_but_gap_and_range_edges_are_excluded(self):
        rows = [self.row("2025-06-29 10:00:00", "2025-06-30 10:00:00"),
                self.row("2025-06-30 11:00:00", "2025-06-30 11:10:00"),
                self.row("2025-06-30 23:55:00", "2025-07-01 00:05:00"),
                self.row("2025-07-31 23:55:00", "2025-08-01 00:05:00"),
                self.row("2025-08-01 12:00:00", "2025-08-01 12:10:00"),
                self.row("2025-08-01 23:55:00", "2025-08-02 00:05:00")]
        out = self.base / "output"
        audit = self.api.run_pipeline([self.source(2025, rows)], "2025-06-29", "2025-08-01", out)
        exact = pd.read_parquet(out / "exact_events_2025.parquet")
        self.assertEqual((exact.main_departures.sum(), exact.main_returns.sum()), (3, 3))
        self.assertEqual(audit["anomalies"]["main_excluded_gap_or_range_edge"], 3)
        june_return = exact[exact.event_time.eq(pd.Timestamp("2025-06-30 10:00:00"))]
        self.assertEqual(june_return.main_returns.sum(), 1)
        july = exact[exact.event_time.dt.month.eq(7)]
        self.assertEqual(july.main_departures.sum() + july.main_returns.sum(), 0)
        self.assertGreater(july.departures.sum() + july.returns.sum(), 0)

    def test_invalid_datetimes_blank_stations_and_duplicate_paths_are_audited(self):
        rows = [self.row("2024-01-01 10:00:00", "2024-01-01 10:05:00"),
                self.row("2024-01-01 11:00:00", "2024-01-01 11:05:00", " ", "2"),
                self.row("2024-01-01 99:00:00", "2024-01-01 12:05:00")]
        path = self.source(2024, rows)
        audit = self.api.run_pipeline([path], "2024-01-01", "2024-01-01", self.base / "output")
        self.assertEqual((audit["raw_rows"], audit["clean_rows"]), (3, 1))
        self.assertEqual(audit["anomalies"]["invalid_datetime"], 1)
        self.assertEqual(audit["anomalies"]["missing_station_id"], 1)
        with self.assertRaisesRegex(ValueError, "Duplicate source"):
            self.api.run_pipeline([path, path], "2024-01-01", "2024-01-01", self.base / "not_published")
        self.assertFalse((self.base / "not_published").exists())

    def test_reference_failures_keep_marked_staging_and_never_publish(self):
        path = self.source(2024, [self.row("2024-01-01 10:00:00", "2024-01-01 10:05:00")])
        bad_schema = self.base / "bad_schema.xlsx"
        duplicate = self.base / "duplicate.xlsx"
        with pd.ExcelWriter(bad_schema) as writer:
            pd.DataFrame({"wrong_column": ["1"]}).to_excel(writer, sheet_name="2024년", index=False)
        with pd.ExcelWriter(duplicate) as writer:
            pd.DataFrame({"터미널번호": ["1", "1"]}).to_excel(writer, sheet_name="2024년", index=False)
        for name, ref, error in [("missing", self.base / "missing.xlsx", FileNotFoundError),
                                  ("schema", bad_schema, KeyError), ("duplicate", duplicate, ValueError)]:
            with self.subTest(reference=name):
                out = self.base / f"failed_{name}"
                with self.assertRaises(error):
                    self.api.run_pipeline([path], "2024-01-01", "2024-01-01", out, station_reference=ref)
                self.assertFalse(out.exists())
                stages = list(self.base.glob(out.name + ".staging-*"))
                self.assertEqual(len(stages), 1)
                self.assertTrue((stages[0] / "scratch").is_dir())
                self.assertTrue((stages[0] / "FAILED.txt").is_file())

    def test_query_failure_closes_connection_and_preserves_marked_staging(self):
        path = self.source(2024, [self.row("2024-01-01 10:00:00", "2024-01-01 10:05:00")])
        out = self.base / "query_failure"

        class FailingConnection:
            def __init__(self, real):
                self.real = real
                self.closed = False

            def __getattr__(self, name):
                return getattr(self.real, name)

            def execute(self, query):
                if query == "SELECT sum(departures),sum(returns) FROM events":
                    raise RuntimeError("injected event conservation query failure")
                return self.real.execute(query)

            def close(self):
                self.closed = True
                self.real.close()

        connection = FailingConnection(self.api.duckdb.connect())
        self.addCleanup(connection.close)
        with patch.object(self.api.duckdb, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "injected event conservation query failure"):
                self.api.run_pipeline([path], "2024-01-01", "2024-01-01", out)
        self.assertFalse(out.exists())
        stages = list(self.base.glob(out.name + ".staging-*"))
        self.assertEqual(len(stages), 1)
        self.assertTrue((stages[0] / "FAILED.txt").is_file())
        self.assertTrue(any((stages[0] / "scratch").glob("events_*.parquet")))
        self.assertTrue(connection.closed, "DuckDB connection must close after query failure")
        with self.assertRaises(self.api.duckdb.ConnectionException):
            connection.real.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
