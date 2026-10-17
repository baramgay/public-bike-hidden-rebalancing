"""재배치 전략 비교 실험: 검증기간에서 목표 배율을 고르고, 시험기간에서 예산별 결과를 낸다.

전략(λ = 거점·일 필요 대수 q의 추정, 목표 계산은 모두 같은 시간 단위 q 공식):
- none        : 재배치 없음(예산 0)
- rule4w      : 최근 4주 같은 요일 실제 시간대 대여·반납 평균으로 계산한 q (AI 없는 경험 규칙)
- ai          : 머신러닝 시간대 예측(전날 자정 기준)으로 계산한 q
- ai_fair     : ai + 취약 거점 아침 최소 대수 보장
- oracle      : 그날 실제 시간대 대여·반납으로 계산한 q (예측이 완벽할 때의 상한)
λ = alpha * q + beta. alpha, beta는 검증기간 기준 예산에서 전략별로 고른다(시험기간 결과를 보지 않음).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate_rebalancing import DAY, Trips, q_from_hourly, route_km, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHAINS = ROOT / "data" / "processed" / "bike_chains"
FORECAST = ROOT / "data" / "processed" / "forecast"
OUT = ROOT / "data" / "processed" / "rebalancing_sim"
PERIODS = {"validation": ("2024-10-01", "2024-12-31"), "test": ("2025-01-01", "2025-06-30")}
DEPOT = 243            # 누비자운영센터
PLAN_HOURS = range(2, 24)
ALPHAS = (0.8, 1.0, 1.25, 1.5, 2.0)
BETAS = (0.0, 1.0, 2.0)
BUDGETS = (0, 250, 500, 750, 1000, 1250, 1500, 1750, 2000, 2500)
TRUCK_CAPACITY = 20
# 전략: λ 출처, 최소보장 집단, 보장 대수, 가중 집단, 가중치. 형평 변형은 같은 출처의 조정값(alpha, beta)을 그대로 쓴다.
STRATEGIES = {
    "none": (None, None, 0, None, 1.0),
    "rule4w": ("rule4w", None, 0, None, 1.0),
    "rule4w_fair": ("rule4w", "취약", 2, None, 1.0),
    "ai": ("ai", None, 0, None, 1.0),
    "ai_fair": ("ai", "취약", 2, None, 1.0),
    "ai_weather": ("ai_weather", None, 0, None, 1.0),
    "ai_weather_fair": ("ai_weather", "취약", 2, None, 1.0),
    "oracle": ("oracle", None, 0, None, 1.0),
}
SENSITIVITY_BUDGET = 1500
SENSITIVITY = {
    "ai_fair_g3": ("ai", "취약", 3, None, 1.0),
    "ai_fair_both": ("ai", "복합취약", 2, None, 1.0),
    "ai_fair_w15": ("ai", None, 0, "취약", 1.5),
}


def epoch_s(x) -> np.ndarray:
    return (pd.to_datetime(x).astype("datetime64[s]").astype("int64")).to_numpy(dtype=float) \
        if isinstance(x, pd.Series) else np.asarray(x, dtype="datetime64[s]").astype("int64").astype(float)


def load_inputs(start: str, end: str, con: duckdb.DuckDBPyConnection):
    # 재생은 초기재고 시각(첫날 02:00)부터. 00~02시 이용은 초기재고·반납 예정에 이미 반영(v2 수정, R01)
    t0 = pd.Timestamp(start) + pd.Timedelta(hours=2)
    trips = con.execute(f"""
        select o, d, ts, te from '{(CHAINS / 'trips_valid.parquet').as_posix()}'
        where ts >= timestamp '{t0}' and ts < timestamp '{end}' + interval 1 day + interval 2 hour
        order by ts""").df()
    # 시작 시각(첫날 02:00)의 자전거 위치: 진행 중 이용은 반납 예정, 나머지는 다음 대여 출발 거점(7일 이내)
    pos = con.execute(f"""
        with b as (
          select bike,
                 arg_min(case when ts >= timestamp '{t0}' then o end, case when ts >= timestamp '{t0}' then ts end) as next_o,
                 min(case when ts >= timestamp '{t0}' then ts end) as next_ts,
                 max(case when ts < timestamp '{t0}' and te > timestamp '{t0}' then te end) as pending_te,
                 arg_max(case when ts < timestamp '{t0}' and te > timestamp '{t0}' then d end,
                         case when ts < timestamp '{t0}' and te > timestamp '{t0}' then te end) as pending_d
          from '{(CHAINS / 'trips_valid.parquet').as_posix()}'
          where te > timestamp '{t0}' - interval 30 day and ts < timestamp '{t0}' + interval 30 day
          group by bike)
        select * from b""").df()
    return trips, pos, t0


def hourly_counts(con, start: str, end: str) -> pd.DataFrame:
    return con.execute(f"""
        with dep as (select o as sid, cast(ts as date) as day, hour(ts) as hr, count(*) as n
                     from '{(CHAINS / 'trips_valid.parquet').as_posix()}'
                     where ts >= timestamp '{start}' and ts < timestamp '{end}' + interval 1 day group by all),
             ret as (select d as sid, cast(te as date) as day, hour(te) as hr, count(*) as n
                     from '{(CHAINS / 'trips_valid.parquet').as_posix()}'
                     where te >= timestamp '{start}' and te < timestamp '{end}' + interval 1 day group by all)
        select coalesce(dep.sid, ret.sid) as sid, coalesce(dep.day, ret.day) as day, coalesce(dep.hr, ret.hr) as hr,
               coalesce(dep.n, 0) as dep, coalesce(ret.n, 0) as ret
        from dep full join ret on dep.sid = ret.sid and dep.day = ret.day and dep.hr = ret.hr""").df()


def q_table(hourly: pd.DataFrame, dep_col: str, ret_col: str, sid_index: dict) -> dict:
    """hourly(sid, day, hr, dep, ret) → {day: q array(거점 순서)}; 02~23시만 사용."""
    h = hourly[hourly["hr"].isin(PLAN_HOURS)]
    out = {}
    hours = list(PLAN_HOURS)
    for day, g in h.groupby("day"):
        piv_d = g.pivot_table(index="sid", columns="hr", values=dep_col, aggfunc="sum").reindex(columns=hours, fill_value=0).fillna(0)
        piv_r = g.pivot_table(index="sid", columns="hr", values=ret_col, aggfunc="sum").reindex(columns=hours, fill_value=0).fillna(0)
        piv_r = piv_r.reindex(piv_d.index, fill_value=0)
        q = q_from_hourly(piv_d.to_numpy(float), piv_r.to_numpy(float))
        arr = np.zeros(len(sid_index))
        for sid, v in zip(piv_d.index, q):
            if sid in sid_index:
                arr[sid_index[sid]] = v
        out[pd.Timestamp(day)] = arr
    return out


def rule4w_hourly(hourly_hist: pd.DataFrame, days: list[pd.Timestamp]) -> pd.DataFrame:
    """각 날짜의 최근 4주 같은 요일 시간대 평균(관측된 날만; 결측 날짜는 빠진다)."""
    hh = hourly_hist.copy()
    hh["day"] = pd.to_datetime(hh["day"])
    rows = []
    for day in days:
        prev = [day - pd.Timedelta(weeks=k) for k in range(1, 5)]
        g = hh[hh["day"].isin(prev)]
        n_obs = g["day"].nunique()
        if n_obs == 0:
            continue
        m = g.groupby(["sid", "hr"], as_index=False)[["dep", "ret"]].sum()
        m[["dep", "ret"]] /= n_obs
        m["day"] = day
        rows.append(m)
    return pd.concat(rows, ignore_index=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-validation", default=str(FORECAST / "selected_predictions_validation.parquet"))
    ap.add_argument("--pred-test", default=str(FORECAST / "selected_predictions_test.parquet"))
    ap.add_argument("--groups", default=str(OUT / "station_groups.csv"),
                    help="station_id, group 열(취약 등). 없으면 고지대 사분위만 사용")
    ap.add_argument("--q-pred-validation", default=str(FORECAST / "q_pred_validation.parquet"),
                    help="거점·일 q 직접 예측(station_id, day, q_rule4w, q_ai, q_ai_oracle_weather, q_actual)")
    ap.add_argument("--q-pred-test", default=str(FORECAST / "q_pred_test.parquet"))
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()
    t_start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{(ROOT / '.tmp').as_posix()}'")

    stations = pd.read_csv(CHAINS / "stations.csv")
    all_trips_sids = con.execute(f"select distinct o from '{(CHAINS / 'trips_valid.parquet').as_posix()}' "
                                 f"union select distinct d from '{(CHAINS / 'trips_valid.parquet').as_posix()}'").df()
    sids = sorted(set(all_trips_sids.iloc[:, 0].astype(int)))
    sid_index = {s: i for i, s in enumerate(sids)}
    st = stations.set_index("station_id").reindex(sids)
    lat0, lon0 = 35.22, 128.65
    xy = np.column_stack([(st["lon"].fillna(lon0) - lon0) * 111.32 * np.cos(np.radians(lat0)),
                          (st["lat"].fillna(lat0) - lat0) * 110.57]).astype(float)
    elev = st["elev_m"].to_numpy()
    hill_cut = np.nanquantile(stations.loc[~stations["is_ops_center"], "elev_m"], 0.75)
    groups = {"고지대(상위25%)": np.nan_to_num(elev, nan=-1) >= hill_cut}
    gpath = Path(args.groups)
    if gpath.exists():
        gdf = pd.read_csv(gpath)
        for gname, gg in gdf.groupby("group"):
            mask = np.zeros(len(sids), bool)
            for s in gg["station_id"].astype(int):
                if s in sid_index:
                    mask[sid_index[s]] = True
            groups[gname] = mask
    fair_group = "취약" if "취약" in groups else "고지대(상위25%)"

    results = []
    q_files = {}
    station_rows = []
    night_rows = []
    tuned = {}
    for split in ("validation", "test"):
        start, end = PERIODS[split]
        trips, pos, t0 = load_inputs(start, end, con)
        tr = Trips(ts=epoch_s(trips["ts"]), o=trips["o"].map(sid_index).to_numpy(),
                   te=epoch_s(trips["te"]), d=trips["d"].map(sid_index).to_numpy())
        pend = pos[pos["pending_te"].notna()]
        pending = [(float(np.datetime64(t, "s").astype("int64")), sid_index[int(dd)])
                   for t, dd in zip(pend["pending_te"], pend["pending_d"])]
        avail = pos[pos["pending_te"].isna() & pos["next_ts"].notna()
                    & (pos["next_ts"] <= t0 + pd.Timedelta(days=7))]
        init = np.bincount(avail["next_o"].astype(int).map(sid_index), minlength=len(sids))
        days = list(pd.date_range(start, end, freq="D"))
        day_starts = [float(np.datetime64(d, "s").astype("int64")) for d in days]
        period_end = day_starts[-1] + DAY + 2 * 3600

        hist = hourly_counts(con, str((pd.Timestamp(start) - pd.Timedelta(days=35)).date()), end)
        hist = hist[hist["sid"].isin(sid_index)]
        q_oracle = q_table(hist[pd.to_datetime(hist["day"]) >= pd.Timestamp(start)], "dep", "ret", sid_index)
        q_rule = q_table(rule4w_hourly(hist, days), "dep", "ret", sid_index)
        qpath = Path(args.q_pred_validation if split == "validation" else args.q_pred_test)
        qinfo = {}
        if qpath.exists():
            qp = pd.read_parquet(qpath)
            qp["day"] = pd.to_datetime(qp["day"])
            qp["sid"] = qp["station_id"].astype(int)
            qp = qp[qp["sid"].isin(sid_index)]
            qp["idx"] = qp["sid"].map(sid_index).astype(int)
            by_day = {d: g for d, g in qp.groupby("day")}

            def from_file(col):
                out = {}
                for d in days:
                    arr = q_rule.get(d, np.zeros(len(sids))).copy()      # 파일에 없는 거점은 시뮬레이터 규칙값
                    g = by_day.get(d)
                    if g is not None:
                        arr[g["idx"].to_numpy()] = g[col].to_numpy(float)
                    out[d] = arr
                return out
            q_rule_sim = q_rule
            q_ai = from_file("q_ai")
            q_ai_weather = from_file("q_ai_oracle_weather")
            q_rule = from_file("q_rule4w")
            # 예측 파일의 실제 q가 시뮬레이터 정의(시간대 공식)와 같은지 대조
            worst = 0.0
            for d in days:
                g = by_day.get(d)
                if g is not None:
                    sim_q = q_oracle.get(d, np.zeros(len(sids)))[g["idx"].to_numpy()]
                    worst = max(worst, float(np.abs(g["q_actual"].to_numpy(float) - sim_q).max()))
            qinfo = {"file": str(qpath), "rows": int(len(qp)), "max_abs_diff_q_actual_vs_sim": worst,
                     "station_days_missing_in_file": int(sum(len(sids) - (len(by_day[d]) if d in by_day else 0)
                                                             for d in days))}
            del q_rule_sim
        else:
            pred = pd.read_parquet(args.pred_validation if split == "validation" else args.pred_test)
            pred["sid"] = pred["station_id"].astype(int)
            pred["day"] = pred["event_time"].dt.normalize()
            pred["hr"] = pred["event_time"].dt.hour
            q_ai = q_table(pred, "pred_departures", "pred_returns", sid_index)
            q_ai_weather = q_ai
            qinfo = {"file": "hourly predictions (q from hourly)", "pred": args.pred_test}
        q_files[split] = qinfo
        sources = {"rule4w": q_rule, "ai": q_ai, "ai_weather": q_ai_weather, "oracle": q_oracle}
        # 거점·일 대상 여부(모든 전략 공통, 누출 없음): 직전 28일 중 대여·반납이 1건 이상, 운영센터 제외
        act = hist.assign(day=pd.to_datetime(hist["day"])).groupby(["day", "sid"]).size().unstack(fill_value=0) > 0
        act = act.reindex(columns=sids, fill_value=False)
        act = act.reindex(pd.date_range(act.index.min(), end, freq="D"), fill_value=False)
        elig_df = act.astype(int).rolling(28, min_periods=1).sum().shift(1).fillna(0) > 0
        ops = np.isin(sids, list(stations.loc[stations["is_ops_center"], "station_id"]))
        elig = {d: elig_df.loc[d].to_numpy() & ~ops for d in days}
        stable = np.logical_and.reduce([elig[d] for d in days])   # 기간 내내 대상인 거점(빈 시간 지표 모수)

        def run(spec: tuple, budget: int, alpha: float, beta: float):
            source, ggroup, g, wgroup, wval = spec
            if source is None or budget == 0:
                lam = {}
            else:
                lam = {ds: (alpha * sources[source][d] + beta) * elig[d]
                       for d, ds in zip(days, day_starts) if d in sources[source]}
            # 보장도 λ와 같은 대상 거점(직전 28일 활동, 운영센터 제외)에만 — 휴면 거점에 배치하지 않음(v2 수정, R02)
            guar = ({ds: np.where(groups[ggroup] & elig[d], g, 0) for d, ds in zip(days, day_starts)}
                    if ggroup else None)
            weight = np.where(groups[wgroup], wval, 1.0) if wgroup else None
            return simulate(tr, init, pending, day_starts, lam, budget, guarantee=guar, weight=weight,
                            period_end=period_end)

        if split == "validation":
            ref_budget = 1500
            for strategy in ("rule4w", "ai", "ai_weather", "oracle"):
                best = None
                for a in ALPHAS:
                    for b in BETAS:
                        r = run(STRATEGIES[strategy], ref_budget, a, b)
                        rate = r.total_served / r.total_demand
                        results.append({"split": split, "strategy": strategy, "budget": ref_budget, "alpha": a, "beta": b,
                                        "served": r.total_served, "demand": r.total_demand, "served_rate": rate})
                        if best is None or rate > best[0] + 1e-12:
                            best = (rate, a, b)
                tuned[strategy] = {"alpha": best[1], "beta": best[2], "validation_served_rate": best[0]}
            for name, spec in list(STRATEGIES.items()) + list(SENSITIVITY.items()):
                if spec[0] and name not in tuned:
                    tuned[name] = dict(tuned[spec[0]])
            print("tuned", json.dumps(tuned, ensure_ascii=False), flush=True)
            continue

        # 시험기간: 예산별 결과 (한 번만 실행)
        plan = [(name, spec, bud) for name, spec in STRATEGIES.items()
                for bud in ((0,) if spec[0] is None else BUDGETS[1:])]
        plan += [(name, spec, SENSITIVITY_BUDGET) for name, spec in SENSITIVITY.items()]
        for strategy, spec, budget in plan:
            if True:
                a, b = (1.0, 0.0) if spec[0] is None else (tuned[strategy]["alpha"], tuned[strategy]["beta"])
                r = run(spec, budget, a, b)
                moves = [sum(p.values()) for _, p, _ in r.moves_per_night]
                km = [route_km(p, dd, xy, sid_index[DEPOT], TRUCK_CAPACITY) for _, p, dd in r.moves_per_night]
                row = {"split": split, "strategy": strategy, "budget": budget, "alpha": a, "beta": b,
                       "served": r.total_served, "demand": r.total_demand, "served_rate": r.total_served / r.total_demand,
                       "moves_per_night": float(np.mean(moves)) if moves else 0.0,
                       "truck_km_per_night": float(np.mean(km)) if km else 0.0,
                       "zero_service_hours_per_station_day": float(r.zero_service_s[stable].sum() / 3600 / stable.sum() / len(days))}
                for gname, mask in list(groups.items()) + [("그외(비취약)", ~groups[fair_group])]:
                    dem = r.served[mask].sum() + r.lost[mask].sum()
                    row[f"served_rate[{gname}]"] = r.served[mask].sum() / dem if dem else np.nan
                    m2 = mask & stable
                    row[f"zero_hours_per_station_day[{gname}]"] = r.zero_service_s[m2].sum() / 3600 / m2.sum() / len(days)
                results.append(row)
                print(strategy, budget, round(row["served_rate"], 4), round(row["moves_per_night"], 1),
                      round(row["truck_km_per_night"], 1), flush=True)
                if budget in (0, 1500) or (strategy == "none"):
                    for i, s in enumerate(sids):
                        station_rows.append({"strategy": strategy, "budget": budget, "station_id": s,
                                             "served": int(r.served[i]), "lost": int(r.lost[i]),
                                             "zero_service_hours": r.zero_service_s[i] / 3600})
                    for ds, p, dd in r.moves_per_night:
                        night_rows.append({"strategy": strategy, "budget": budget,
                                           "day": pd.Timestamp(ds, unit="s").date(),
                                           "moves": sum(p.values()),
                                           "pickup_stations": len(p), "drop_stations": len(dd)})

    res = pd.DataFrame(results)
    res.to_csv(OUT / f"results_{args.tag}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(station_rows).to_csv(OUT / f"station_results_{args.tag}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(night_rows).to_csv(OUT / f"nightly_moves_{args.tag}.csv", index=False, encoding="utf-8-sig")
    meta = {"tuned": tuned, "periods": PERIODS, "budgets": BUDGETS, "plan_hours": [min(PLAN_HOURS), max(PLAN_HOURS)],
            "truck_capacity": TRUCK_CAPACITY, "depot": DEPOT, "fair_group": fair_group,
            "strategies": STRATEGIES, "sensitivity": SENSITIVITY, "q_inputs": q_files,
            "groups": {k: int(v.sum()) for k, v in groups.items()}, "stations": len(sids),
            "stable_stations_last_split": int(stable.sum()),
            "pred_validation": args.pred_validation, "pred_test": args.pred_test,
            "runtime_s": round(time.time() - t_start, 1)}
    (OUT / f"meta_{args.tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
