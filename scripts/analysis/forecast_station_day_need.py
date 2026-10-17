"""거점·일 '필요 대수' q 직접 예측(재배치 시뮬레이터 입력).

q(거점, 날) = max_k ( Σ_{h<=k} 대여_h − Σ_{h<k} 반납_h ), h = 02~23시, 0 이상. 같은 시간 안에서는 대여 먼저.
시뮬레이터(simulate_rebalancing.q_from_hourly)와 같은 정의다.

예측 시점: 그날 00시. 특징은 전날까지의 관측만 쓴다(누출 없음). 단, 공휴일은 미리 알려진 달력 정보다.
- ai          : 누출 없는 모형(전날 날씨까지)
- ai_weather  : ai + 당일 관측 날씨(기상예보가 정확하다는 가정의 상한 성격, 배포 시 예보값으로 대체)
- rule4w      : 최근 4주 같은 요일 q 평균(경험 규칙)
분할: 학습 2023-02-01~2024-09-30 / 검증 2024-10-01~12-31(모형·설정 선택) / 시험 2025-01-01~06-30(고정 모형으로 1회 예측).
날씨: ASOS 155 일자료. 일 강수 빈칸 685일 중 684일은 강수 현상 기록이 없어 무강수(0)로, 1일(2023-11-29, 1분 비)은 측정 불가 미량(0)으로 둔다.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate_rebalancing import q_from_hourly  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHAINS = ROOT / "data" / "processed" / "bike_chains"
OUT = ROOT / "data" / "processed" / "forecast"
ASOS = ROOT / "data" / "raw" / "approved_public_apis" / "20261016T150727234763Z" / "derived_csv"
SPLITS = {"train": ("2023-02-01", "2024-09-30"), "validation": ("2024-10-01", "2024-12-31"),
          "test": ("2025-01-01", "2025-06-30")}
HOURS = list(range(2, 24))
OPS = {243, 327}
# 관공서 공휴일(KASI 표 + 발표 후 지정분: 2023-05-29 대체, 2023-10-02·2024-10-01·2025-01-27 임시, 2024-04-10·2025-06-03 선거)
HOLIDAYS = pd.to_datetime([
    "2023-01-01", "2023-01-21", "2023-01-22", "2023-01-23", "2023-01-24", "2023-03-01", "2023-05-05", "2023-05-27",
    "2023-05-29", "2023-06-06", "2023-08-15", "2023-09-28", "2023-09-29", "2023-09-30", "2023-10-02", "2023-10-03",
    "2023-10-09", "2023-12-25",
    "2024-01-01", "2024-02-09", "2024-02-10", "2024-02-11", "2024-02-12", "2024-03-01", "2024-04-10", "2024-05-05",
    "2024-05-06", "2024-05-15", "2024-06-06", "2024-08-15", "2024-09-16", "2024-09-17", "2024-09-18", "2024-10-01",
    "2024-10-03", "2024-10-09", "2024-12-25",
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-01", "2025-03-03", "2025-05-05",
    "2025-05-06", "2025-06-03", "2025-06-06", "2025-08-15", "2025-10-03", "2025-10-05", "2025-10-06", "2025-10-07",
    "2025-10-08", "2025-10-09", "2025-12-25"])
PARAMS = dict(loss="poisson", learning_rate=0.05, max_iter=400, max_leaf_nodes=31, min_samples_leaf=40,
              l2_regularization=1.0, random_state=42)


def station_day_table() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{(ROOT / '.tmp').as_posix()}'")
    trips = (CHAINS / "trips_valid.parquet").as_posix()
    h = con.execute(f"""
        with dep as (select o as sid, cast(ts as date) as day, hour(ts) as hr, count(*) as n from '{trips}' group by all),
             ret as (select d as sid, cast(te as date) as day, hour(te) as hr, count(*) as n from '{trips}' group by all)
        select coalesce(dep.sid, ret.sid) as sid, coalesce(dep.day, ret.day) as day, coalesce(dep.hr, ret.hr) as hr,
               coalesce(dep.n, 0) as dep, coalesce(ret.n, 0) as ret
        from dep full join ret on dep.sid = ret.sid and dep.day = ret.day and dep.hr = ret.hr""").df()
    h["day"] = pd.to_datetime(h["day"])
    daily = h.groupby(["sid", "day"], as_index=False)[["dep", "ret"]].sum()
    hp = h[h["hr"].isin(HOURS)]
    dep = hp.pivot_table(index=["sid", "day"], columns="hr", values="dep", aggfunc="sum", fill_value=0).reindex(columns=HOURS, fill_value=0)
    ret = hp.pivot_table(index=["sid", "day"], columns="hr", values="ret", aggfunc="sum", fill_value=0).reindex(columns=HOURS, fill_value=0)
    ret = ret.reindex(dep.index, fill_value=0)
    q = pd.Series(q_from_hourly(dep.to_numpy(float), ret.to_numpy(float)), index=dep.index, name="q").reset_index()
    t = daily.merge(q, on=["sid", "day"], how="left").fillna({"q": 0.0})
    # 관측된 출발일 달력(7월 결측 구분): 출발 기록이 있는 날만 '관측일'
    obs_days = set(h.loc[h["dep"] > 0, "day"].dt.normalize().unique())
    return t, obs_days


def full_panel(t: pd.DataFrame, obs_days: set) -> pd.DataFrame:
    days = pd.date_range("2023-01-01", "2025-06-30", freq="D")
    sids = sorted(set(t["sid"]) - OPS)
    idx = pd.MultiIndex.from_product([sids, days], names=["sid", "day"])
    p = t.set_index(["sid", "day"]).reindex(idx).reset_index()
    p["observed_day"] = p["day"].isin(obs_days)
    # 관측일인데 기록이 없는 거점·일은 0(이용 없음), 결측일은 NaN 유지
    for c in ("dep", "ret", "q"):
        p.loc[p["observed_day"] & p[c].isna(), c] = 0.0
    return p


def add_features(p: pd.DataFrame) -> pd.DataFrame:
    p = p.sort_values(["sid", "day"]).copy()
    g = p.groupby("sid", sort=False)
    for k in (1, 7, 14, 21, 28):
        p[f"q_lag{k}"] = g["q"].shift(k)
    p["q_rule4w"] = p[["q_lag7", "q_lag14", "q_lag21", "q_lag28"]].mean(axis=1, skipna=True)
    p["q_rule4w_std"] = p[["q_lag7", "q_lag14", "q_lag21", "q_lag28"]].std(axis=1, skipna=True)
    p["q_mean7"] = g["q"].transform(lambda s: s.shift(1).rolling(7, min_periods=3).mean())
    p["q_mean28"] = g["q"].transform(lambda s: s.shift(1).rolling(28, min_periods=7).mean())
    p["q_max28"] = g["q"].transform(lambda s: s.shift(1).rolling(28, min_periods=7).max())
    for c in ("dep", "ret"):
        p[f"{c}_lag1"] = g[c].shift(1)
        p[f"{c}_lag7"] = g[c].shift(7)
        p[f"{c}_mean28"] = g[c].transform(lambda s: s.shift(1).rolling(28, min_periods=7).mean())
    p["net_mean28"] = p["dep_mean28"] - p["ret_mean28"]
    act28 = g["dep"].transform(lambda s: (s.shift(1).fillna(0) + 0).rolling(28, min_periods=1).sum()) + \
        g["ret"].transform(lambda s: s.shift(1).fillna(0).rolling(28, min_periods=1).sum())
    p["eligible"] = act28 > 0                                   # 시뮬레이터와 같은 대상 규칙
    city = p.groupby("day")[["dep"]].sum().rename(columns={"dep": "city_dep"})
    city["city_dep_lag1"] = city["city_dep"].shift(1)
    city["city_dep_lag7"] = city["city_dep"].shift(7)
    p = p.merge(city[["city_dep_lag1", "city_dep_lag7"]], left_on="day", right_index=True, how="left")
    p["dow"] = p["day"].dt.dayofweek
    p["month"] = p["day"].dt.month
    p["holiday"] = p["day"].isin(HOLIDAYS).astype(int)
    p["holiday_prev"] = (p["day"] - pd.Timedelta(days=1)).isin(HOLIDAYS).astype(int)
    p["holiday_next"] = (p["day"] + pd.Timedelta(days=1)).isin(HOLIDAYS).astype(int)
    p["offday"] = ((p["dow"] >= 5) | (p["holiday"] == 1)).astype(int)
    return p


def weather() -> pd.DataFrame:
    w = pd.concat([pd.read_csv(ASOS / f"asos155_daily_{y}.csv") for y in (2023, 2024, 2025)])
    w["day"] = pd.to_datetime(w["tm"])
    w["rain"] = w["sumRn"].fillna(0.0)          # 빈칸 = 무강수(현상 기록 없음 684일) 또는 측정 불가 미량(1일)
    w = w[["day", "rain", "avgTa", "maxTa", "avgWs"]].sort_values("day")
    w["rain_flag"] = (w["rain"] >= 1.0).astype(int)
    lag = w.set_index("day").shift(1).add_suffix("_prev").reset_index()
    return w.merge(lag, on="day")


LEAKFREE = ["q_lag1", "q_lag7", "q_lag14", "q_lag21", "q_lag28", "q_rule4w", "q_rule4w_std", "q_mean7", "q_mean28",
            "q_max28", "dep_lag1", "dep_lag7", "dep_mean28", "ret_lag1", "ret_lag7", "ret_mean28", "net_mean28",
            "city_dep_lag1", "city_dep_lag7", "dow", "month", "holiday", "holiday_prev", "holiday_next", "offday",
            "rain_prev", "avgTa_prev", "maxTa_prev", "elev_m"]
WEATHER_TODAY = ["rain", "rain_flag", "avgTa", "maxTa", "avgWs"]


def mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    t, obs_days = station_day_table()
    p = add_features(full_panel(t, obs_days)).merge(weather(), on="day", how="left")
    st = pd.read_csv(CHAINS / "stations.csv")[["station_id", "elev_m"]].rename(columns={"station_id": "sid"})
    p = p.merge(st, on="sid", how="left")
    p = p[p["eligible"] & p["observed_day"] & p["q"].notna()].copy()
    p["split"] = "none"
    for name, (a, b) in SPLITS.items():
        p.loc[(p["day"] >= a) & (p["day"] <= b), "split"] = name
    p = p[p["split"] != "none"]

    tr = p[p["split"] == "train"]
    models = {}
    for name, feats in (("ai", LEAKFREE), ("ai_weather", LEAKFREE + WEATHER_TODAY)):
        m = HistGradientBoostingRegressor(categorical_features=[feats.index("dow"), feats.index("month")], **PARAMS)
        m.fit(tr[feats], tr["q"])
        models[name] = (m, feats)
        p[f"q_{name}"] = m.predict(p[feats])
    p["q_rule4w_filled"] = p["q_rule4w"].fillna(p["q_mean28"]).fillna(0.0)

    rows = []
    for split in ("train", "validation", "test"):
        s = p[p["split"] == split]
        for col, label in (("q_rule4w_filled", "rule4w"), ("q_lag7", "lag7"), ("q_ai", "ai"), ("q_ai_weather", "ai_weather")):
            pred = s[col].fillna(s["q_rule4w_filled"])
            err = np.abs(pred - s["q"])
            rows.append({"split": split, "model": label, "station_days": len(s), "mae": float(err.mean()),
                         "within2": float((err <= 2).mean()), "under_by3plus": float((s["q"] - pred >= 3).mean()),
                         "total_q": float(s["q"].sum()), "total_pred": float(pred.sum())})
            if split == "test":
                continue
        # 비·공휴일 구간별(검증·시험)
    metrics = pd.DataFrame(rows)
    seg = []
    for split in ("validation", "test"):
        s = p[p["split"] == split]
        for seg_name, mask in (("비 오는 날(≥1mm)", s["rain"] >= 1), ("맑은 날", s["rain"] < 1),
                               ("휴일·주말", s["offday"] == 1), ("평일", s["offday"] == 0)):
            ss = s[mask]
            for col, label in (("q_rule4w_filled", "rule4w"), ("q_ai", "ai"), ("q_ai_weather", "ai_weather")):
                seg.append({"split": split, "segment": seg_name, "model": label, "station_days": len(ss),
                            "mae": mae(ss[col], ss["q"])})
    seg = pd.DataFrame(seg)

    metrics.to_csv(OUT / "q_metrics.csv", index=False, encoding="utf-8-sig")
    seg.to_csv(OUT / "q_metrics_segments.csv", index=False, encoding="utf-8-sig")
    for split in ("validation", "test"):
        s = p[p["split"] == split]
        out = pd.DataFrame({"station_id": s["sid"].astype(int), "day": s["day"].dt.date,
                            "q_rule4w": s["q_rule4w_filled"], "q_ai": s["q_ai"], "q_ai_oracle_weather": s["q_ai_weather"],
                            "q_actual": s["q"]})
        out.to_parquet(OUT / f"q_pred_{split}.parquet", index=False)
    imp = {}
    lock = {"created_kst": pd.Timestamp.now().isoformat(timespec="seconds"), "splits": SPLITS, "params": PARAMS,
            "features_ai": LEAKFREE, "features_ai_weather_extra": WEATHER_TODAY,
            "selection": "검증기간 지표로 확인 후 고정. 시험기간은 같은 고정 모형으로 1회 예측",
            "train_rows": int(len(tr)), "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "runtime_s": round(time.time() - t0, 1)}
    (OUT / "q_model_lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metrics.round(4).to_string())
    print(seg.pivot_table(index=["split", "segment"], columns="model", values="mae").round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
