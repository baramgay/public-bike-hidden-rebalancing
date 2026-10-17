"""보고서 수치의 통계적 근거 보강: 3가지 검정 (seed 42, 재현 가능).

1) 예측 오차 차이(시험기간): 날짜 단위 클러스터 부트스트랩 CI, 날짜별 MAE 비교, Wilcoxon 부호순위
2) 형평 효과의 거점 단위 쌍대 검정: ai vs ai_fair(취약·비취약), ai vs rule4w(전체) — 예산 1,500
3) 의존도 회귀: moved_in/rentals ~ 고도 + 취약 + log(대여) + 구 고정효과, WLS + HC1

입력은 읽기만 한다(data/raw 미사용). 출력 data/processed/stats/stat_tests.json.
재실행하면 같은 결과가 나온다(난수 seed 42). 기존 산출물(results_v2.csv, q_metrics.csv)과 대조해
다르면 AssertionError로 멈춘다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
import statsmodels
import statsmodels.api as sm
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "data" / "processed"
OUT = P / "stats" / "stat_tests.json"
SEED, B, BLOCK = 42, 2000, 7
BUDGET = 1500
EPS = 1e-12


def ci(a: np.ndarray) -> list[float]:
    return [float(v) for v in np.percentile(a, [2.5, 97.5])]


def wilcoxon(d: np.ndarray) -> dict:
    d = np.where(np.abs(d) < EPS, 0.0, d)
    nz = int((d != 0).sum())
    if nz == 0:
        return {"n_nonzero": 0, "wilcoxon_p": None}
    return {"n_nonzero": nz, "wilcoxon_p": float(stats.wilcoxon(d).pvalue)}


# ---------------------------------------------------------------- 1) 예측 오차
def day_idx(rng, D: int, block: int) -> np.ndarray:
    """날짜 인덱스 재표본 (B, D). block=1이면 날짜 단순 복원추출, >1이면 원형 이동블록."""
    if block == 1:
        return rng.integers(0, D, (B, D))
    nb = -(-D // block)
    start = rng.integers(0, D, (B, nb))
    return ((start[:, :, None] + np.arange(block)) % D).reshape(B, -1)[:, :D]


def forecast() -> dict:
    q = pd.read_parquet(P / "forecast" / "q_pred_test.parquet")
    cols = {"rule4w": "q_rule4w", "ai": "q_ai", "ai_weather": "q_ai_oracle_weather"}
    assert not q[list(cols.values()) + ["q_actual"]].isna().any().any()
    err = pd.DataFrame({k: (q[c] - q["q_actual"]).abs() for k, c in cols.items()})
    err["day"] = q["day"].to_numpy()
    S = err.groupby("day").sum()[list(cols)].to_numpy()          # (D, 3) 날짜별 절대오차 합
    n = err.groupby("day").size().to_numpy().astype(float)       # 날짜별 거점 수
    D = len(n)
    mae = S.sum(0) / n.sum()
    ref = pd.read_csv(P / "forecast" / "q_metrics.csv").query("split=='test'").set_index("model")["mae"]
    for k, m in zip(cols, mae):
        assert abs(m - ref[k]) < 1e-9, f"MAE 불일치 {k}: {m} vs {ref[k]}"

    daily = S / n[:, None]
    res = {"period": [str(q["day"].min()), str(q["day"].max())], "n_station_days": int(len(q)), "n_days": D,
           "n_boot": B, "seed": SEED, "unit": "대(q: 아침 최소 필요 대수)",
           "bootstrap": "날짜 복원추출(클러스터), 거점·일 평균=날짜별 합계/거점·일 수",
           "mae": dict(zip(cols, map(float, mae)))}
    boots = {}
    for tag, blk in (("", 1), (f"_block{BLOCK}", BLOCK)):
        idx = day_idx(np.random.default_rng(SEED), D, blk)
        boots[tag] = S[idx].sum(1) / n[idx].sum(1)[:, None]      # (B, 3) 재표본 MAE
    for k in ("ai", "ai_weather"):
        j, r = list(cols).index(k), list(cols).index("rule4w")
        d = daily[:, j] - daily[:, r]
        out = {"mae_diff": float(mae[j] - mae[r]), "reduction_pct": float((mae[r] - mae[j]) / mae[r] * 100)}
        for tag, bm in boots.items():
            out[f"mae_diff_ci95{tag}"] = ci(bm[:, j] - bm[:, r])
            out[f"reduction_pct_ci95{tag}"] = ci((bm[:, r] - bm[:, j]) / bm[:, r] * 100)
        out["daily"] = {"n_days": D, "n_days_better": int((d < 0).sum()), "share_days_better": float((d < 0).mean()),
                        "median_daily_diff": float(np.median(d)), **wilcoxon(d)}
        res[f"{k}_vs_rule4w"] = out
    return res


# ---------------------------------------------------------------- 2) 거점 단위 쌍대 검정
def paired(x0, x1, better: str, rng, s0=None, s1=None, dem=None) -> dict:
    """x0=기준, x1=비교. diff=x1-x0. better='lower'|'higher'. s0,s1,dem 주어지면 수요가중 합산 성공률 차이도."""
    x0, x1 = np.asarray(x0, float), np.asarray(x1, float)
    d = x1 - x0
    n = len(d)
    idx = rng.integers(0, n, (B, n))
    sign = -1 if better == "lower" else 1
    out = {"n": n, "mean_base": float(x0.mean()), "mean_alt": float(x1.mean()),
           "mean_diff": float(d.mean()), "ci95_mean_diff": ci(d[idx].mean(1)),
           "median_diff": float(np.median(d)), "ci95_median_diff": ci(np.median(d[idx], axis=1)),
           "diff_quantiles": dict(zip(("p10", "p25", "p75", "p90"), map(float, np.percentile(d, [10, 25, 75, 90])))),
           "share_improved": float((sign * d > EPS).mean()), "share_worse": float((sign * d < -EPS).mean()),
           "share_unchanged": float((np.abs(d) <= EPS).mean()), **wilcoxon(d)}
    if dem is not None:
        s0, s1, dem = (np.asarray(a, float) for a in (s0, s1, dem))
        r0, r1 = s0.sum() / dem.sum(), s1.sum() / dem.sum()
        bd = (s1[idx].sum(1) - s0[idx].sum(1)) / dem[idx].sum(1)
        out["pooled"] = {"rate_base": float(r0), "rate_alt": float(r1), "diff": float(r1 - r0), "ci95_diff": ci(bd),
                         "note": "수요 가중(거점 합산) 성공률. 거점 부트스트랩"}
    return out


def station_tables():
    meta = json.loads((P / "rebalancing_sim" / "meta_v2.json").read_text(encoding="utf-8"))
    lo, hi = meta["periods"]["test"]
    n_days = len(pd.date_range(lo, hi))
    res = pd.read_csv(P / "rebalancing_sim" / "station_results_v2.csv")
    res = res[res["budget"] == BUDGET]
    wide = {}
    for s in ("ai", "ai_fair", "rule4w"):
        t = res[res["strategy"] == s].set_index("station_id").sort_index()
        wide[s] = t
    dem = wide["ai"]["served"] + wide["ai"]["lost"]
    for s, t in wide.items():
        assert (t["served"] + t["lost"]).equals(dem), f"{s}: 수요(대여 시도) 불일치"
    q = pd.read_parquet(P / "forecast" / "q_pred_test.parquet")
    cnt = q.groupby("station_id")["day"].nunique()
    stable = set(cnt[cnt == n_days].index)                       # 시험기간 내내 대상 거점(러너 stable과 동일)
    assert len(stable) == meta["stable_stations_last_split"], (len(stable), meta["stable_stations_last_split"])
    g = pd.read_csv(P / "rebalancing_sim" / "station_groups.csv")
    vuln = set(g.loc[g["group"] == "취약", "station_id"])
    assert len(vuln) == meta["groups"]["취약"]
    idx = dem.index
    is_st = idx.isin(stable)
    is_v = idx.isin(vuln)
    # 대조: results_v2.csv(시험, 예산 1,500)의 집단 지표와 일치해야 함
    r2 = pd.read_csv(P / "rebalancing_sim" / "results_v2.csv").query("split=='test' and budget==@BUDGET")
    for s in wide:
        row = r2[r2["strategy"] == s].iloc[0]
        t = wide[s]
        checks = {
            "zero_service_hours_per_station_day": t["zero_service_hours"][is_st].sum() / is_st.sum() / n_days,
            "served_rate": t["served"].sum() / dem.sum(),
            "zero_hours_per_station_day[취약]": t["zero_service_hours"][is_st & is_v].sum() / (is_st & is_v).sum() / n_days,
            "served_rate[취약]": t["served"][is_v].sum() / dem[is_v].sum(),
            "zero_hours_per_station_day[그외(비취약)]": t["zero_service_hours"][is_st & ~is_v].sum() / (is_st & ~is_v).sum() / n_days,
            "served_rate[그외(비취약)]": t["served"][~is_v].sum() / dem[~is_v].sum(),
        }
        for k, v in checks.items():
            assert abs(v - row[k]) < 1e-9, f"results_v2 불일치 {s} {k}: {v} vs {row[k]}"
    return wide, dem, is_st, is_v, n_days, meta


def station_pairs(wide, dem, is_st, is_v, n_days, base: str, alt: str, groups: dict) -> dict:
    """groups: 이름 -> 거점 마스크(전체 거점 기준). 빈 시간은 '기간 내내 대상' 거점만, 성공률은 수요>0 거점."""
    out = {}
    for name, m in groups.items():
        rng = np.random.default_rng(SEED)
        h = m & is_st
        r = m & (dem.to_numpy() > 0)
        hrs = {s: wide[s]["zero_service_hours"].to_numpy() / n_days for s in (base, alt)}
        rate = {s: wide[s]["served"].to_numpy() / dem.to_numpy().clip(min=1) for s in (base, alt)}
        out[name] = {
            "empty_hours_per_station_day": paired(hrs[base][h], hrs[alt][h], "lower", rng),
            "success_rate": paired(rate[base][r], rate[alt][r], "higher", rng,
                                   wide[base]["served"].to_numpy()[r], wide[alt]["served"].to_numpy()[r],
                                   dem.to_numpy()[r]),
        }
    return out


def equity_and_ai_vs_rule() -> tuple[dict, dict]:
    wide, dem, is_st, is_v, n_days, meta = station_tables()
    allm = np.ones(len(dem), bool)
    common = {"period": meta["periods"]["test"], "budget_per_night": BUDGET, "n_days": n_days, "n_boot": B, "seed": SEED,
              "n_stations_sim": int(len(dem)), "n_stable_stations": int(is_st.sum()),
              "stable_rule": "시험기간 181일 내내 대상(직전 28일 활동, 운영센터 제외)인 거점 = q_pred_test에 모든 날짜가 있는 거점. "
                             "results_v2.csv의 빈 시간 지표 모수와 동일(441곳). 빈 시간은 이 거점만, 성공률은 수요>0 전 거점(러너와 동일)",
              "reproduces_results_v2": True,
              "diff_definition": "비교 전략 − 기준 전략. 빈 시간은 음수, 성공률은 양수가 개선"}
    eq = {**common, "base": "ai", "alt": "ai_fair",
          **station_pairs(wide, dem, is_st, is_v, n_days, "ai", "ai_fair", {"vulnerable": is_v, "non_vulnerable": ~is_v})}
    # 민감도: 취약 거점 성공률을 '기간 내내 대상' 거점으로 한정
    rng = np.random.default_rng(SEED)
    m = is_v & is_st & (dem.to_numpy() > 0)
    rt = lambda s: wide[s]["served"].to_numpy()[m] / dem.to_numpy()[m]  # noqa: E731
    eq["vulnerable_stable_only_success_rate"] = paired(rt("ai"), rt("ai_fair"), "higher", rng,
                                                       wide["ai"]["served"].to_numpy()[m],
                                                       wide["ai_fair"]["served"].to_numpy()[m], dem.to_numpy()[m])
    ar = {**common, "base": "rule4w", "alt": "ai",
          **station_pairs(wide, dem, is_st, is_v, n_days, "rule4w", "ai", {"all": allm})}
    return eq, ar


# ---------------------------------------------------------------- 3) 의존도 회귀
def flag(s: pd.Series) -> np.ndarray:
    v = s.map({True: 1, False: 0, "True": 1, "False": 0})
    assert v.notna().all()
    return v.to_numpy(float)


def fit_row(res, names) -> dict:
    cf = res.conf_int()
    return {n: {"coef": float(res.params[i]), "se_hc1": float(res.bse[i]), "ci95": [float(cf[i, 0]), float(cf[i, 1])],
                "p": float(res.pvalues[i])} for i, n in enumerate(names)}


def dependency() -> dict:
    f = pd.read_csv(P / "bike_chains" / "station_year_flows.csv")
    f = f[f["year"] == 2024]
    steps = {"year2024_rows": int(len(f))}
    f = f[f["rentals"] >= 365]
    steps["rentals_ge_365"] = int(len(f))
    st = pd.read_csv(P / "bike_chains" / "stations.csv")[["station_id", "district", "elev_m", "is_ops_center"]]
    v = pd.read_csv(P / "accessibility_scenarios" / "station_vulnerability.csv")[
        ["station_id", "classified", "vulnerable", "vulnerable_both"]]
    d = f[["station_id", "rentals", "moved_in"]].merge(st, on="station_id", how="left").merge(v, on="station_id", how="left")
    assert d["elev_m"].notna().all() and d["district"].notna().all(), "stations.csv에 없는 거점"
    d = d[~d["is_ops_center"].astype(bool)]
    steps["after_ops_center_excluded"] = int(len(d))
    d = d[d["classified"].eq(True)].copy()
    steps["after_classified_only"] = int(len(d))
    d["dep"] = d["moved_in"] / d["rentals"]
    d["elev10"] = d["elev_m"] / 10
    d["vulnerable"], d["vulnerable_both"] = flag(d["vulnerable"]), flag(d["vulnerable_both"])
    d["log_rentals"] = np.log(d["rentals"])
    fe = pd.get_dummies(d["district"], prefix="구", drop_first=True, dtype=float)
    ref = sorted(d["district"].unique())[0]
    out = {"sample_steps": steps, "n": int(len(d)), "outcome": "의존도 = moved_in / rentals (2024, 0~1 비율)",
           "outcome_mean": float(d["dep"].mean()), "outcome_mean_weighted": float(np.average(d["dep"], weights=d["rentals"])),
           "estimator": "WLS(가중치=대여 수), 이분산 강건 표준오차 HC1, t분포 95% CI",
           "units": {"elev10": "고도 10m 상승당", "log_rentals": "ln(연 대여) 1 증가당", "vulnerable": "비취약 대비 단일 취약(복합 제외 효과)",
                     "vulnerable_both": "취약 거점 중 복합취약의 추가분"},
           "district_reference": ref, "r2_note": "WLS 가중 결정계수"}
    specs = {"main": ["elev10", "vulnerable", "vulnerable_both", "log_rentals"], "elev_only": ["elev10", "log_rentals"]}
    for key, vars_ in specs.items():
        X = pd.concat([d[vars_], fe], axis=1)
        X.insert(0, "const", 1.0)
        res = sm.WLS(d["dep"].to_numpy(), X.to_numpy(float), weights=d["rentals"].to_numpy(float)).fit(cov_type="HC1", use_t=True)
        names = list(X.columns)
        m = {"n": int(res.nobs), "r2": float(res.rsquared), "r2_adj": float(res.rsquared_adj), "coef": fit_row(res, names)}
        if key == "main":
            R = np.zeros(len(names))
            R[names.index("vulnerable")] = R[names.index("vulnerable_both")] = 1
            t = res.t_test(R)
            c = t.conf_int()[0]
            m["composite_vs_nonvulnerable"] = {"coef": float(np.squeeze(t.effect)), "ci95": [float(c[0]), float(c[1])],
                                               "p": float(np.squeeze(t.pvalue)), "note": "vulnerable + vulnerable_both"}
        out[key] = m
    bins = pd.cut(d["elev_m"], [-np.inf, 10, 20, 30, 50, 80, np.inf], labels=["<=10m", "10-20m", "20-30m", "30-50m", "50-80m", ">80m"])
    out["elev_bin_means"] = {str(k): {"n": int(len(g)), "dep_mean": float(g["dep"].mean()),
                                      "dep_mean_weighted": float(np.average(g["dep"], weights=g["rentals"]))}
                             for k, g in d.groupby(bins, observed=True)}
    out["spearman_elev_vs_vulnerability"] = {}
    for col in ("vulnerable", "vulnerable_both"):
        r = stats.spearmanr(d["elev_m"], d[col])
        out["spearman_elev_vs_vulnerability"][col] = {"rho": float(r.statistic), "p": float(r.pvalue), "n": int(len(d)),
                                                      "share_flagged": float(d[col].mean())}
    return out


def main() -> int:
    eq, ar = equity_and_ai_vs_rule()
    out = {"meta": {"seed": SEED, "n_boot": B, "block_days_sensitivity": BLOCK,
                    "versions": {"numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                                 "statsmodels": statsmodels.__version__},
                    "note": "관찰 자료의 연관성 검정. 인과 효과가 아님. 시험기간 시뮬레이션 결과는 모형 가정 하의 값"},
           "forecast": forecast(), "equity_station": eq, "ai_vs_rule_station": ar, "dependency_regression": dependency()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
