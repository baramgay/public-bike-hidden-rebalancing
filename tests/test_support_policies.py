"""Conditional start-buffer allocation; no inventory or causal interpretation."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/analysis/compare_support_policies.py"


class SupportPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.exists(), "support policy implementation is missing")
        spec = importlib.util.spec_from_file_location("support_policies", MODULE)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

    def need(self, q=(3, 1), vulnerable=(False, True)):
        return pd.DataFrame({"station_id": ["1", "2"], "q": q, "vulnerable": vulnerable})

    def test_exact_order_and_conservative_timestamp_ties(self):
        self.assertEqual(self.api.required_start_buffer([1, 0], [0, 1]), 1)
        self.assertEqual(self.api.required_start_buffer([0, 1], [1, 0]), 0)
        self.assertEqual(self.api.required_start_buffer([], []), 0)
        self.assertEqual(self.api.required_start_buffer([1], [1]), 1)
        self.assertEqual(self.api.required_start_buffer([1], [1], tie_order="returns_first"), 0)
        for d, r in [([-1], [0]), ([1], []), ([np.nan], [0])]:
            with self.assertRaises(ValueError):
                self.api.required_start_buffer(d, r)

    def test_proportional_hamilton_tie_id_and_budget_conservation(self):
        allocated, status = self.api.allocate_support(self.need(), 2, 0)
        self.assertEqual(allocated.b.tolist(), [2, 0])
        self.assertEqual(status["unused"], 0)
        shuffled, _ = self.api.allocate_support(self.need().iloc[::-1], 2, 0)
        pd.testing.assert_frame_equal(allocated, shuffled)
        allocated, status = self.api.allocate_support(self.need(), 10, 0)
        self.assertEqual(allocated.b.tolist(), [3, 1])
        self.assertEqual(status["unused"], 6)
        self.assertEqual(allocated.b.sum() + status["unused"], 10)
        self.assertTrue(pd.api.types.is_integer_dtype(allocated.b))
        for budget in [-1, 1.5]:
            with self.assertRaises(ValueError):
                self.api.allocate_support(self.need(), budget, 0)

    def test_minimum_first_and_distinct_failure_states(self):
        allocated, status = self.api.allocate_support(self.need(), 2, .5)
        self.assertEqual(allocated.b.tolist(), [1, 1])
        self.assertEqual(status["status"], "ok")
        for need, expected in [(self.need(vulnerable=(False, False)), "empty_vulnerable_set"),
                               (self.need(q=(3, 0)), "zero_vulnerable_need"),
                               (self.need(), "infeasible_minimum")]:
            budget = 5 if expected == "infeasible_minimum" else 2
            allocated, status = self.api.allocate_support(need, budget, 1)
            self.assertEqual(status["status"], expected)
            self.assertTrue(allocated.b.isna().all())
        _, status = self.api.allocate_support(self.need(q=(0, 0)), 3, 0)
        self.assertEqual(status["unused"], 3)
        _, status = self.api.allocate_support(self.need(), 2, .5, classification_ready=False)
        self.assertEqual(status["status"], "classification_unready")

    def test_equal_linear_efficiency_has_vulnerable_allocation_range(self):
        envelope = self.api.efficiency_tie_envelope(self.need(q=(3, 3)), 2)
        self.assertEqual(envelope["max_predicted_fulfillment"], 2)
        self.assertEqual(envelope["vulnerable_min"], 0)
        self.assertEqual(envelope["vulnerable_max"], 2)
        self.assertTrue(envelope["multiple_equivalent_allocations"])
        self.assertEqual(self.api.efficiency_tie_envelope(self.need(q=(3, 1)), 8)["vulnerable_min"], 1)

    def test_metrics_zero_denominators_and_capped_lower_quartile(self):
        observed = self.need(q=(0, 2))
        allocation = pd.DataFrame({"station_id": ["1", "2"], "b": [3, 1]})
        metrics = self.api.evaluate_support(allocation, observed)
        self.assertEqual(metrics["fulfilled_start_buffers"], 1)
        self.assertEqual(metrics["shortfall_start_buffers"], 1)
        self.assertEqual(metrics["station_day_complete_fraction"], .5)
        self.assertEqual(metrics["fulfillment_ratio_q25"], .5)
        self.assertEqual(metrics["vulnerable_fulfillment_rate"], .5)
        zero = self.api.evaluate_support(allocation, self.need(q=(0, 0)))
        self.assertTrue(np.isnan(zero["fulfillment_rate"]))
        self.assertTrue(np.isnan(zero["fulfillment_ratio_q25"]))
        capped = self.api.evaluate_support(allocation, self.need(q=(1, 1)))
        self.assertEqual(capped["fulfillment_ratio_q25"], 1)
        with self.assertRaises(ValueError):
            self.api.evaluate_support(allocation.iloc[:1], observed)

    def test_exact_parquet_matches_hand_calculation_including_empty_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            events = pd.DataFrame({"station_id": ["1", "1", "2"],
                                   "event_time": pd.to_datetime(["2024-10-01 01:00", "2024-10-01 02:00", "2024-10-01 01:00"]),
                                   "departures": [2, 0, 1], "returns": [1, 1, 1],
                                   "main_departures": [1, 0, 1], "main_returns": [1, 0, 1],
                                   "coverage_status": "observed_departure_date"})
            masks = pd.DataFrame({"station_id": ["1", "2", "3", "4"],
                                  "target_date": pd.to_datetime(["2024-10-01"] * 4),
                                  "eligible_asof": [True, True, True, False], "history_complete_28": True})
            events.to_parquet(base / "events.parquet", index=False)
            masks.to_parquet(base / "masks.parquet", index=False)
            self.api.build_observed_q(base / "events.parquet", base / "masks.parquet", base / "q.parquet", "2024-10-01", "2024-10-01")
            q = pd.read_parquet(base / "q.parquet")
            self.assertEqual(q.station_id.tolist(), ["1", "2", "3"])
            self.assertEqual(q.q.tolist(), [1, 1, 0])
            self.assertEqual(q.q_returns_first.tolist(), [0, 0, 0])
            self.assertEqual(q.q_all_records.tolist(), [2, 1, 0])
            self.assertEqual(q.q_all_returns_first.tolist(), [1, 0, 0])
            self.assertIn("q_hourly_net_lower_bound", q)
            self.assertEqual(q.q_hourly_net_lower_bound.tolist(), [0, 0, 0])

    def test_prediction_curves_require_every_station_hour_and_safe_cutoff(self):
        predictions = pd.DataFrame({"station_id": "1", "event_time": pd.date_range("2024-10-01", periods=24, freq="h"),
                                    "cutoff": pd.Timestamp("2024-10-01"), "pred_departures": 0., "pred_returns": 0.})
        predictions.loc[0, ["pred_departures", "pred_returns"]] = [1.2, .5]
        q = self.api.predicted_q(predictions)
        self.assertEqual(q.q.iloc[0], 1.2)
        self.assertEqual(q.q_capacity.iloc[0], 2)
        for bad in [predictions.iloc[:-1], pd.concat([predictions, predictions.iloc[:1]])]:
            with self.assertRaises(ValueError):
                self.api.predicted_q(bad)
        predictions.loc[0, "cutoff"] = pd.Timestamp("2024-10-02")
        with self.assertRaises(ValueError):
            self.api.predicted_q(predictions)

    def test_budget_lock_and_block_bootstrap_are_deterministic(self):
        daily = pd.DataFrame({"target_date": pd.date_range("2024-10-01", periods=3), "q": [10, 20, 30]})
        self.assertEqual(self.api.freeze_budgets(daily)["budgets"], {"10": 2, "25": 5, "50": 10})
        daily["q"] = 5
        self.assertEqual(self.api.freeze_budgets(daily)["budgets"]["10"], 1)
        daily["target_date"] = pd.date_range("2025-01-01", periods=3)
        with self.assertRaises(ValueError):
            self.api.freeze_budgets(daily)
        series = pd.DataFrame({"target_date": pd.date_range("2025-01-01", periods=21), "fulfilled_start_buffers": range(21)})
        first = self.api.block_bootstrap(series, "fulfilled_start_buffers")
        self.assertEqual(first, self.api.block_bootstrap(series, "fulfilled_start_buffers"))
        self.assertEqual(first["resamples"], 1000)
        self.assertLessEqual(first["lower"], first["upper"])

    def test_all_rules_are_capacity_bounded_and_no_silent_prediction_drop(self):
        self.assertTrue(hasattr(self.api, "match_daily_predictions"), "strict daily matching is missing")
        need = self.need(q=(.2, 2.1))
        for rule in ["proportional", "uniform", "station_id"]:
            allocated, status = self.api.allocate_support(need, 7, 0, rule=rule)
            self.assertEqual(allocated.b.tolist(), [1, 3])
            self.assertEqual(status["used"] + status["unused"], 7)
            self.assertTrue(allocated.b.le(allocated.q_capacity).all())
        with self.assertRaises(ValueError):
            self.api.match_daily_predictions(pd.DataFrame({"station_id": ["1"], "target_date": [pd.Timestamp("2024-10-01")], "q": [2]}),
                                              pd.DataFrame({"station_id": ["1", "2"], "target_date": [pd.Timestamp("2024-10-01")] * 2, "q": [2, 1]}))

    def test_real_equity_gate_does_not_create_internal_labels(self):
        self.assertTrue(hasattr(self.api, "compare_day"), "daily policy comparison is missing")
        need = self.need().drop(columns="vulnerable")
        result = self.api.compare_day(need, need, 2, classification_ready=False)
        self.assertEqual(set(result.policy), {"uniform", "proportional", "station_id", "balanced_10", "balanced_20", "balanced_30"})
        balanced = result[result.policy.str.startswith("balanced")]
        self.assertTrue(balanced.status.eq("classification_unready").all())
        self.assertTrue(balanced.fulfilled_start_buffers.isna().all())
        self.assertTrue(result.loc[~result.policy.str.startswith("balanced"), "fulfilled_start_buffers"].eq(2).all())

    def test_lock_rejects_changed_validation_and_requires_explicit_review(self):
        self.assertTrue(hasattr(self.api, "verify_policy_gate"), "review/hash gate is missing")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "validation_lock.json").write_text('{}')
            with self.assertRaises(ValueError):
                self.api.verify_policy_gate(base, base / "forecast", task3_reviewed=False)
            (base / "validation_lock.sha256").write_text("incorrect")
            with self.assertRaises(ValueError):
                self.api.verify_policy_gate(base, base / "forecast", task3_reviewed=True)

    def test_gate_binds_real_forecast_selection_metadata(self):
        self.assertTrue(hasattr(self.api, "verify_policy_gate"))
        with tempfile.TemporaryDirectory() as tmp:
            import hashlib
            import json
            base = Path(tmp)
            forecast = base / "forecast"
            forecast.mkdir()
            observed = base / "observed_q_validation.parquet"
            observed.write_bytes(b"frozen-validation")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            lock = base / "validation_lock.json"
            lock.write_text(json.dumps({"inputs_sha256": {}, "observed_validation_sha256": digest(observed)}))
            (base / "validation_lock.sha256").write_text(digest(lock))
            selection = forecast / "model_selection.json"
            selection.write_text('{"chosen_model": "baseline"}')
            (forecast / "audit.json").write_text(json.dumps({"selection_sha256": digest(selection)}))
            _, result = self.api.verify_policy_gate(base, forecast, task3_reviewed=True)
            self.assertEqual(result["forecast_selection_sha256"], digest(selection))
            selection.write_text('{"chosen_model": "tampered"}')
            with self.assertRaises(ValueError):
                self.api.verify_policy_gate(base, forecast, task3_reviewed=True)


if __name__ == "__main__":
    unittest.main()
