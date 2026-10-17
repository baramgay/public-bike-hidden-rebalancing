"""Conditional start-buffer comparison, never inventory/failure reconstruction.

The validation-only preparation command cannot read 2025 exact events. Test-period
evaluation is a separate, explicit gate and requires frozen validation artifacts.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math

import duckdb
import numpy as np
import pandas as pd


def required_start_buffer(departures, returns, tie_order="departures_first"):
    """Maximum positive deficit, with all departures first inside a timestamp.

    Exact timestamps provide the evaluation; hourly predictions have lower temporal
    resolution and cannot identify ordering within each hour.
    """
    d, r = np.asarray(departures, dtype=float), np.asarray(returns, dtype=float)
    if d.ndim != 1 or r.ndim != 1 or len(d) != len(r):
        raise ValueError("equal one-dimensional departure/return sequences required")
    if not np.isfinite(d).all() or not np.isfinite(r).all() or (d < 0).any() or (r < 0).any():
        raise ValueError("finite nonnegative event counts required")
    if tie_order not in {"departures_first", "returns_first"}:
        raise ValueError("unknown timestamp tie order")
    if not len(d):
        return 0
    cumulative = np.cumsum(d - r)
    peaks = cumulative + r if tie_order == "departures_first" else cumulative
    result = float(max(0., peaks.max()))
    return int(result) if result.is_integer() else result


def _need(need):
    if not {"station_id", "q"}.issubset(need):
        raise ValueError("station_id and q required")
    data = need.copy()
    if data.station_id.isna().any():
        raise ValueError("missing station_id")
    data["station_id"] = data.station_id.astype(str)
    if data.station_id.duplicated().any():
        raise ValueError("one row per station required")
    q = data.q.to_numpy(dtype=float)
    if not np.isfinite(q).all() or (q < 0).any():
        raise ValueError("finite nonnegative q required")
    data["q_raw"] = q
    data["q_capacity"] = np.ceil(q).astype(np.int64)
    return data.sort_values("station_id", kind="stable").reset_index(drop=True)


def _budget(budget):
    if isinstance(budget, (bool, np.bool_)) or not np.isfinite(budget) or int(budget) != budget or budget < 0:
        raise ValueError("nonnegative integer budget required")
    return int(budget)


def _hamilton(capacities, budget):
    """Capacity proportional Hamilton allocation; input already in ID order."""
    capacities = np.asarray(capacities, dtype=np.int64)
    total = int(capacities.sum())
    used = min(budget, total)
    if not total:
        return np.zeros(len(capacities), dtype=np.int64)
    quotas = capacities.astype(float) * (used / total)
    allocated = np.floor(quotas).astype(np.int64)
    remainder = used - int(allocated.sum())
    order = np.argsort(-(quotas - allocated), kind="stable")
    allocated[order[:remainder]] += 1
    return allocated


def allocate_support(need, budget, minimum_share, *, classification_ready=True, rule="proportional"):
    """Minimum vulnerable share first, then residual-need Hamilton allocation.

    Fractional predicted q is rounded up once. Rounded q determines both weights
    and capacities. Failures have missing b and no implicit relaxed allocation.
    """
    data = _need(need)
    budget = _budget(budget)
    if not np.isfinite(minimum_share) or not 0 <= minimum_share <= 1:
        raise ValueError("minimum_share must be in [0, 1]")
    if rule not in {"proportional", "uniform", "station_id"}:
        raise ValueError("unknown allocation rule")
    required = math.ceil(budget * minimum_share)
    status = {"status": "ok", "budget": budget, "minimum_required": required,
              "minimum_share": float(minimum_share), "rule": rule, "unused": budget,
              "used": 0, "quantization": "ceil_predicted_q_once"}
    def failure(reason):
        data["b"] = pd.Series(pd.NA, index=data.index, dtype="Int64")
        status["status"] = reason
        status["unused"] = None
        status["used"] = None
        return data, status
    vulnerable = np.zeros(len(data), dtype=bool)
    if minimum_share > 0:
        if not classification_ready or "vulnerable" not in data or data.vulnerable.isna().any():
            return failure("classification_unready")
        vulnerable = data.vulnerable.to_numpy(dtype=bool)
        if not vulnerable.any():
            return failure("empty_vulnerable_set")
        if not data.loc[vulnerable, "q_capacity"].sum():
            return failure("zero_vulnerable_need")
        if data.loc[vulnerable, "q_capacity"].sum() < required:
            return failure("infeasible_minimum")
    caps = data.q_capacity.to_numpy()
    b = np.zeros(len(data), dtype=np.int64)
    if required:
        b[vulnerable] = _hamilton(caps[vulnerable], required)
    residual, available = caps - b, budget - int(b.sum())
    if rule == "proportional":
        b += _hamilton(residual, available)
    elif rule == "station_id":
        for i in range(len(b)):
            amount = min(int(residual[i]), available)
            b[i] += amount
            available -= amount
    else:
        # Equal unit rounds among stations still below capacity, ID first on ties.
        while available and (b < caps).any():
            active = np.flatnonzero(b < caps)
            step = min(available // len(active), int((caps - b)[active].min()))
            if step:
                b[active] += step
                available -= step * len(active)
            else:
                b[active[:available]] += 1
                available -= min(available, len(active))
    data["b"] = b
    status["used"] = int(b.sum())
    status["unused"] = budget - status["used"]
    status["capacity_limited"] = bool(status["unused"])
    return data, status


def efficiency_tie_envelope(need, budget):
    """Vulnerable support range across all maximum linear-utility allocations.

    Unit marginal utilities are identical up to integer q capacities. The range
    is diagnostic, not a separate efficiency optimization method.
    """
    data = _need(need)
    budget = _budget(budget)
    if "vulnerable" not in data or data.vulnerable.isna().any():
        return {"status": "classification_unready"}
    v = int(data.loc[data.vulnerable.astype(bool), "q_capacity"].sum())
    other = int(data.loc[~data.vulnerable.astype(bool), "q_capacity"].sum())
    used = min(budget, v + other)
    low, high = max(0, used - other), min(used, v)
    return {"status": "ok", "max_predicted_fulfillment": used,
            "vulnerable_min": low, "vulnerable_max": high,
            "vulnerable_share_min": low / budget if budget else np.nan,
            "vulnerable_share_max": high / budget if budget else np.nan,
            "multiple_equivalent_allocations": high > low}


def evaluate_support(allocation, observed):
    """Evaluate identical station sets, q=0 excluded only from ratio quantiles."""
    data = _need(observed)
    if allocation.station_id.astype(str).duplicated().any():
        raise ValueError("duplicate allocation station")
    other = allocation[["station_id", "b"]].copy()
    other["station_id"] = other.station_id.astype(str)
    if set(data.station_id) != set(other.station_id):
        raise ValueError("prediction/allocation/observed station sets must match exactly")
    data = data.merge(other, on="station_id", validate="one_to_one")
    b = data.b.to_numpy(dtype=float)
    if not np.isfinite(b).all() or (b < 0).any() or (b != np.floor(b)).any():
        raise ValueError("integer nonnegative allocations required")
    def metrics(frame):
        q, b = frame.q.to_numpy(dtype=float), frame.b.to_numpy(dtype=float)
        fulfilled = float(np.minimum(q, b).sum())
        total = float(q.sum())
        ratios = np.minimum(b[q > 0] / q[q > 0], 1.)
        return {"station_days": len(q), "positive_need_station_days": int((q > 0).sum()),
                "observed_need": total, "fulfilled_start_buffers": fulfilled,
                "shortfall_start_buffers": float(np.maximum(q - b, 0).sum()),
                "fulfillment_rate": fulfilled / total if total else np.nan,
                "station_day_complete_fraction": float((b >= q).mean()) if len(q) else np.nan,
                "fulfillment_ratio_q25": float(np.quantile(ratios, .25)) if len(ratios) else np.nan}
    result = metrics(data)
    if "vulnerable" not in data or data.vulnerable.isna().any():
        result["vulnerable_status"] = "classification_unready"
        for key in metrics(data.iloc[:0]):
            result["vulnerable_" + key] = np.nan
    else:
        vulnerable = data.loc[data.vulnerable.astype(bool)]
        result["vulnerable_status"] = ("empty_vulnerable_set" if vulnerable.empty else
                                        "zero_vulnerable_need" if vulnerable.q.sum() == 0 else "ok")
        result.update({"vulnerable_" + k: v for k, v in metrics(vulnerable).items()})
    return result


def _sql_path(path):
    return "'" + str(Path(path).resolve()).replace("\\", "/").replace("'", "''") + "'"


def build_observed_q(events_path, masks_path, output_path, start, end):
    """Bounded DuckDB exact-timestamp q; eligible masks include zero-event days."""
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start > end or (start.year != end.year):
        raise ValueError("ordered, single-year period required")
    con = duckdb.connect()
    con.execute("SET threads=2")
    con.execute("SET memory_limit='768MB'")
    con.execute("SET preserve_insertion_order=false")
    try:
        con.execute(f"""CREATE TEMP TABLE candidates AS SELECT CAST(station_id AS VARCHAR) station_id,
            CAST(target_date AS DATE) target_date FROM read_parquet({_sql_path(masks_path)})
            WHERE eligible_asof AND history_complete_28
            AND target_date BETWEEN DATE '{start.date()}' AND DATE '{end.date()}'""")
        # Aggregate same timestamp defensively; cum before timestamp + d is the
        # conservative peak, not merely end-of-timestamp cumulative net flow.
        con.execute(f"""CREATE TEMP TABLE ordered_events AS WITH events AS (
            SELECT CAST(e.station_id AS VARCHAR) station_id, CAST(event_time AS DATE) target_date,
                event_time, SUM(main_departures) d, SUM(main_returns) r,
                SUM(departures) da, SUM(returns) ra
            FROM read_parquet({_sql_path(events_path)}) e JOIN candidates c
            ON CAST(e.station_id AS VARCHAR)=c.station_id AND CAST(e.event_time AS DATE)=c.target_date
            WHERE coverage_status='observed_departure_date'
            GROUP BY 1,2,3)
            SELECT *, SUM(d-r) OVER w net_after, SUM(da-ra) OVER w all_net_after
            FROM events WINDOW w AS (PARTITION BY station_id,target_date ORDER BY event_time
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)""")
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"""COPY (WITH hourly_last AS (
            SELECT station_id,target_date,net_after FROM ordered_events
            QUALIFY ROW_NUMBER() OVER (PARTITION BY station_id,target_date,DATE_TRUNC('hour',event_time)
                                      ORDER BY event_time DESC)=1),
            hourly_q AS (SELECT station_id,target_date,GREATEST(0,MAX(net_after)) q_hourly_net_lower_bound
                        FROM hourly_last GROUP BY 1,2)
            SELECT c.station_id,c.target_date,
            CAST(GREATEST(0,COALESCE(MAX(net_after+r),0)) AS BIGINT) q,
            CAST(GREATEST(0,COALESCE(MAX(net_after),0)) AS BIGINT) q_returns_first,
            CAST(GREATEST(0,COALESCE(MAX(all_net_after+ra),0)) AS BIGINT) q_all_records,
            CAST(GREATEST(0,COALESCE(MAX(all_net_after),0)) AS BIGINT) q_all_returns_first,
            COALESCE(SUM(d),0)::BIGINT main_departures,COALESCE(SUM(r),0)::BIGINT main_returns,
            COALESCE(SUM(da),0)::BIGINT all_departures,COALESCE(SUM(ra),0)::BIGINT all_returns,
            COALESCE(MAX(h.q_hourly_net_lower_bound),0)::BIGINT q_hourly_net_lower_bound
            FROM candidates c LEFT JOIN ordered_events e USING(station_id,target_date)
            LEFT JOIN hourly_q h USING(station_id,target_date)
            GROUP BY 1,2 ORDER BY 2,1) TO {_sql_path(output_path)} (FORMAT PARQUET)""")
    finally:
        con.close()


def predicted_q(predictions):
    columns = ["station_id", "event_time", "cutoff", "pred_departures", "pred_returns"]
    if not set(columns).issubset(predictions):
        raise ValueError("missing selected prediction columns")
    data = predictions.copy()
    data["event_time"] = pd.to_datetime(data.event_time)
    data["cutoff"] = pd.to_datetime(data.cutoff)
    if data[columns].isna().any().any():
        raise ValueError("missing predictions forbidden")
    data["target_date"] = data.event_time.dt.normalize()
    if not data.cutoff.eq(data.target_date).all():
        raise ValueError("predictions require matching midnight cutoff")
    if data.duplicated(["station_id", "event_time"]).any():
        raise ValueError("duplicate station-hour prediction")
    records = []
    for (station, date), group in data.groupby(["station_id", "target_date"], sort=True):
        group = group.sort_values("event_time")
        if not np.array_equal(group.event_time.to_numpy(), pd.date_range(date, periods=24, freq="h").to_numpy()):
            raise ValueError("all 24 exact station-hours required")
        q = required_start_buffer(group.pred_departures, group.pred_returns)
        records.append({"station_id": str(station), "target_date": date, "q": float(q),
                        "q_capacity": math.ceil(q), "resolution": "hourly_departures_first_proxy"})
    return pd.DataFrame(records)


def freeze_budgets(observed):
    dates = pd.to_datetime(observed.target_date)
    if observed.empty or not dates.between("2024-10-01", "2024-12-31").all():
        raise ValueError("budgets may use validation 2024Q4 only")
    total = observed.groupby("target_date").q.sum()
    median = float(total.median())
    return {"validation_start": str(dates.min().date()), "validation_end": str(dates.max().date()),
            "validation_days": len(total), "median_daily_observed_q": median,
            "budgets": {str(p): math.floor(median * p / 100 + .5) for p in [10, 25, 50]},
            "rounding": "nearest_integer_half_up", "minimum_shares": [0., .1, .2, .3],
            "vulnerable_thresholds": [.2, .25, .3], "tie_break": "station_id_string_ascending",
            "predicted_q_integerization": "ceil once; integer q used for weights, caps and tie utility",
            "bootstrap_block_days": 7, "bootstrap_resamples": 1000, "bootstrap_seed": 42}


def block_bootstrap(daily, metric, resamples=1000, seed=42):
    """Moving 7-calendar-day blocks; variation in observed period, not causality."""
    series = daily.sort_values("target_date")
    dates = pd.to_datetime(series.target_date)
    if dates.duplicated().any() or not dates.diff().dropna().eq(pd.Timedelta(days=1)).all():
        raise ValueError("one metric per consecutive calendar day required")
    values = series[metric].to_numpy(dtype=float)
    if len(values) < 7 or not np.isfinite(values).all():
        raise ValueError("at least seven finite daily metrics required")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(values) - 6, size=(resamples, math.ceil(len(values) / 7)))
    indices = (starts[:, :, None] + np.arange(7)).reshape(resamples, -1)[:, :len(values)]
    estimates = values[indices].mean(axis=1)
    low, high = np.quantile(estimates, [.025, .975])
    return {"estimate": float(values.mean()), "lower": float(low), "upper": float(high),
            "block_days": 7, "resamples": resamples, "seed": seed,
            "interpretation": "observed-period variation; not a causal policy confidence interval"}


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def match_daily_predictions(predictions_q, observed):
    """Refuse an inner join that could quietly discard missing predictions."""
    keys = ["station_id", "target_date"]
    left, right = predictions_q.copy(), observed.copy()
    for frame in [left, right]:
        frame["station_id"] = frame.station_id.astype(str)
        frame["target_date"] = pd.to_datetime(frame.target_date)
        if frame.duplicated(keys).any():
            raise ValueError("duplicate station-day")
    matched = left[keys].merge(right[keys], on=keys, how="outer", indicator=True)
    if not matched._merge.eq("both").all():
        raise ValueError("missing or unexpected prediction station-day; evaluation aborted")
    return left.sort_values(keys).reset_index(drop=True), right.sort_values(keys).reset_index(drop=True)


def compare_day(predicted, observed, budget, *, classification_ready):
    """One day's predeclared policies, including explicit unready balanced rows."""
    if set(predicted.station_id.astype(str)) != set(observed.station_id.astype(str)):
        raise ValueError("predicted and observed station sets must match")
    records = []
    policies = [("uniform", "uniform", 0.), ("proportional", "proportional", 0.),
                ("station_id", "station_id", 0.)] + [(f"balanced_{share}", "proportional", share / 100) for share in [10, 20, 30]]
    for policy, rule, minimum in policies:
        allocated, status = allocate_support(predicted, budget, minimum,
                                             classification_ready=classification_ready, rule=rule)
        record = {"policy": policy, **status}
        if status["status"] == "ok":
            record.update(evaluate_support(allocated, observed))
            record["predicted_linear_fulfillment"] = int(np.minimum(allocated.b, allocated.q_capacity).sum())
            record["same_predicted_linear_efficiency"] = True
        records.append(record)
    return pd.DataFrame(records)


def verify_policy_gate(output_dir, forecast_dir, *, task3_reviewed=False):
    """Must run before opening any test-event/prediction file."""
    if not task3_reviewed:
        raise ValueError("Task 3 reviewed PASS authorization required before policy evaluation")
    output_dir, forecast_dir = Path(output_dir), Path(forecast_dir)
    lock_path = output_dir / "validation_lock.json"
    recorded = (output_dir / "validation_lock.sha256").read_text(encoding="ascii").strip()
    if _hash(lock_path) != recorded:
        raise ValueError("validation policy lock hash mismatch")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if _hash(output_dir / "observed_q_validation.parquet") != lock["observed_validation_sha256"]:
        raise ValueError("observed validation changed since budget freeze")
    for file, expected in lock["inputs_sha256"].items():
        if _hash(file) != expected:
            raise ValueError("frozen policy input changed: " + file)
    # Only validation selection metadata is inspected at this gate.
    selection = forecast_dir / "model_selection.json"
    if not selection.exists():
        raise FileNotFoundError("forecast validation selection artifact is required")
    forecast_audit = json.loads((forecast_dir / "audit.json").read_text(encoding="utf-8"))
    if _hash(selection) != forecast_audit["selection_sha256"]:
        raise ValueError("forecast selection changed after freeze")
    return lock, {"task3_reviewed": True, "validation_lock_sha256": recorded,
                  "forecast_selection_sha256": _hash(selection), "policy_code_sha256": _hash(__file__)}


def prepare_validation(event_dir, output_dir, accessibility_status):
    """Preparation has no forecast dependency and never opens test events."""
    event_dir, output_dir = Path(event_dir), Path(output_dir)
    lock_path = output_dir / "validation_lock.json"
    if lock_path.exists():
        raise FileExistsError("validation lock exists; preserve frozen result")
    output_dir.mkdir(parents=True, exist_ok=True)
    observed_path = output_dir / "observed_q_validation.parquet"
    build_observed_q(event_dir / "exact_events_2024.parquet", event_dir / "station_day_masks.parquet",
                     observed_path, "2024-10-01", "2024-12-31")
    observed = pd.read_parquet(observed_path)
    lock = freeze_budgets(observed)
    status = json.loads(Path(accessibility_status).read_text(encoding="utf-8"))
    lock["classification_ready"] = bool(status.get("classification_ready", False))
    lock["actual_equity_status"] = "pending_reviewed_predictions_and_classification" if lock["classification_ready"] else "classification_unready"
    lock["phase"] = "validation_only_prepared; heldout_policy_evaluation_not_run"
    lock["code_sha256"] = _hash(__file__)
    lock["inputs_sha256"] = {str(p): _hash(p) for p in [event_dir / "exact_events_2024.parquet",
                             event_dir / "station_day_masks.parquet", Path(accessibility_status)]}
    lock["observed_validation_sha256"] = _hash(observed_path)
    daily = observed.groupby("target_date", as_index=False).agg(
        stations=("q", "size"), q=("q", "sum"), q_returns_first=("q_returns_first", "sum"),
        q_all_records=("q_all_records", "sum"), q_all_returns_first=("q_all_returns_first", "sum"))
    daily.to_csv(output_dir / "validation_daily_q.csv", index=False)
    audit = {"station_days": len(observed), "days": int(observed.target_date.nunique()),
             "stations": int(observed.station_id.nunique()), "zero_q_station_days": int(observed.q.eq(0).sum()),
             "main_q_total": int(observed.q.sum()), "all_records_q_total": int(observed.q_all_records.sum()),
             "returns_first_q_total": int(observed.q_returns_first.sum()),
             "timestamp_tie_changed_station_days": int(observed.q.ne(observed.q_returns_first).sum()),
             "duration_rule_changed_station_days": int(observed.q.ne(observed.q_all_records).sum())}
    (output_dir / "validation_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "validation_lock.sha256").write_text(_hash(lock_path) + "\n", encoding="ascii")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-validation", action="store_true", required=True)
    parser.add_argument("--event-dir", type=Path, default=Path("data/processed/event_panel"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/support_policies"))
    parser.add_argument("--accessibility-status", type=Path, default=Path("data/processed/accessibility_scenarios/status.json"))
    args = parser.parse_args()
    print(json.dumps(prepare_validation(args.event_dir, args.output_dir, args.accessibility_status), indent=2))
