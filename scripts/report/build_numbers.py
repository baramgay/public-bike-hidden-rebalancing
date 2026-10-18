"""보고서에 쓰는 모든 숫자를 분석 출력에서 모아 outputs/report/report_numbers.json으로 저장.

보고서 생성기(build_deck.js)는 이 파일만 읽는다. 숫자를 손으로 옮기지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "data" / "processed"
FIG = ROOT / "outputs" / "report_figures"
OUT = ROOT / "outputs" / "report"


def equal_service(r: pd.DataFrame, ref: str = "rule4w", budget: int = 1500) -> dict:
    """시험기간: 경험 규칙(예산 1500)과 같은 성공률을 내는 데 필요한 밤당 이동 대수·차량 km(예산 곡선을 처음 넘는 구간 선형 보간)."""
    t = r[r["split"] == "test"]
    target = float(t[(t["strategy"] == ref) & (t["budget"] == budget)]["served_rate"].iloc[0])
    out = {"target_served_rate": target}
    for s in ("rule4w", "ai", "ai_weather", "ai_fair", "oracle"):
        c = t[(t["strategy"] == s) & (t["budget"] > 0)].sort_values("budget").reset_index(drop=True)
        i = int((c["served_rate"] >= target).idxmax())
        if c.loc[i, "served_rate"] < target or i == 0:
            continue
        a, b = c.loc[i - 1], c.loc[i]
        w = (target - a["served_rate"]) / (b["served_rate"] - a["served_rate"])
        out[s] = {k: float(a[k] + w * (b[k] - a[k])) for k in ("moves_per_night", "truck_km_per_night")}
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    n: dict = {}
    audit = json.loads((P / "bike_chains" / "audit.json").read_text(encoding="utf-8"))
    n["raw_rows"] = sum(audit["rows"]["raw"].values())
    n["valid_rows"] = sum(audit["rows"]["valid"].values())
    n["pairs"] = audit["rows"]["pairs"]
    n["bikes"] = audit["rows"]["bikes"]

    y = pd.read_csv(P / "bike_chains" / "yearly_summary.csv").set_index("year")
    n["moved_by_year"] = {int(k): int(v) for k, v in y["moved_core"].items()}
    n["moved_share_by_year"] = {int(k): float(v) for k, v in y["moved_core_share_of_judged"].items()}
    n["moved_3y"] = int(y["moved_core"].sum())
    n["judged_3y"] = int(y["judged_pairs"].sum())
    n["moved_share_3y"] = n["moved_3y"] / n["judged_3y"]
    n["median_move_km_2024"] = float(y.loc[2024, "median_km_core"])

    d = pd.read_csv(P / "bike_chains" / "daily_moves.csv", parse_dates=["service_date"])
    d = d[d["service_date"].dt.year.isin([2023, 2024, 2025])]
    n["moved_per_day_by_year"] = {int(k): float(v) for k, v in d.groupby(d["service_date"].dt.year)["moved"].mean().items()}
    n["moved_per_day_3y"] = float(d.loc[d["moved"] > 0, "moved"].mean())
    n["moved_days_3y"] = int((d["moved"] > 0).sum())

    b = pd.read_csv(P / "bike_chains" / "batch_sizes.csv")
    b24 = b[b["year"] == 2024]
    tot = b24["bikes"].sum()
    n["batch5plus_share_2024"] = float(b24.loc[b24["batch"].isin(["5~9대", "10대 이상"]), "bikes"].sum() / tot)
    n["batch_single_share_2024"] = float(b24.loc[b24["batch"] == "1대", "bikes"].sum() / tot)

    e = pd.read_csv(P / "bike_chains" / "elevation_flows.csv")
    e24 = e[e["year"] == 2024].set_index("flow")
    n["ride_down_2024"] = float(e24.loc["rental_trip", "share_down"])
    n["ride_up_2024"] = float(e24.loc["rental_trip", "share_up"])
    n["move_up_2024"] = float(e24.loc["unrecorded_move", "share_up"])
    n["move_down_2024"] = float(e24.loc["unrecorded_move", "share_down"])

    dep = json.loads((FIG / "dependency_bars.json").read_text(encoding="utf-8"))
    n["dependency_rows"] = dep["rows"]
    hs = json.loads((FIG / "hourly_share.json").read_text(encoding="utf-8"))
    n["moved_share_8am"] = hs["by_hour"]["8"]

    f = pd.read_csv(P / "bike_chains" / "station_year_flows.csv")
    f = f[f["year"] == 2024].copy()
    f["dep"] = f["moved_in"] / f["rentals"].where(f["rentals"] > 0)
    keys = {159: "성주 유니온빌리지", 162: "창원중앙역", 377: "자은에일린의 뜰", 346: "감계푸르지오 정류소", 123: "상남오거리"}
    n["stations"] = {name: {"dependency": float(f.loc[f["station_id"] == sid, "dep"].iloc[0]),
                            "elev_m": float(f.loc[f["station_id"] == sid, "elev_m"].iloc[0]),
                            "rentals_2024": int(f.loc[f["station_id"] == sid, "rentals"].iloc[0])}
                     for sid, name in keys.items()}

    km = pd.read_csv(P / "rebalancing_sim" / "observed_truck_km_yearly.csv").set_index("year")
    n["truck_km_per_day_2024_cap20"] = float(km.loc[2024, "km_cap20_per_day"])
    n["truck_km_year_2024_cap20"] = float(km.loc[2024, "km_cap20_year"])

    v = pd.read_csv(P / "accessibility_scenarios" / "station_vulnerability.csv")
    c = v[v["classified"].astype(str) == "True"]
    n["vuln_classified"] = int(len(c))
    n["vuln_count"] = int((c["vulnerable"].astype(str) == "True").sum())
    n["vuln_both_count"] = int((c["vulnerable_both"].astype(str) == "True").sum())
    both = c[c["vulnerable_both"].astype(str) == "True"]
    n["vuln_both_median_bus_tph"] = float(both["bus_trips_per_hour_300m"].median())
    n["vuln_both_median_care_m"] = float(both["nearest_primary_care_m"].median())
    n["vuln_both_median_pharmacy_m"] = float(both["nearest_pharmacy_m"].median())

    n["example_bike"] = json.loads((FIG / "example_bike_4503.json").read_text(encoding="utf-8"))

    sim = P / "rebalancing_sim" / "results_v2.csv"            # v2 = 경계·보장 대상 수정판(policy_lock_v2.json)
    n["simulation_available"] = sim.exists()
    if sim.exists():
        n["simulation"] = json.loads(pd.read_csv(sim).to_json(orient="records", force_ascii=False))   # NaN → null
        n["simulation_meta"] = json.loads((P / "rebalancing_sim" / "meta_v2.json").read_text(encoding="utf-8"))
        n["equal_service"] = equal_service(pd.read_csv(sim))
    # 차량 배출계수(kgCO2/km): 1톤 경유 화물차 공인 연비 8.6~9.9km/L × 경유 2.60kg/L, 전기 화물차 3.1km/kWh × 0.4149
    # 출처: docs/research/rebalancing_carbon_evidence.md
    n["co2_kg_per_km"] = {"diesel_low": 0.263, "diesel_high": 0.302, "ev": 0.134}
    n["observed_co2_t_2024"] = {k: n["truck_km_year_2024_cap20"] * v / 1000 for k, v in n["co2_kg_per_km"].items()}
    n["fig"] = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(FIG.glob("*.json"))}
    stats = P / "stats" / "stat_tests.json"                    # scripts/analysis/stat_tests.py
    if stats.exists():
        n["stats"] = json.loads(stats.read_text(encoding="utf-8"))
    council = P / "civic_text" / "llm" / "summary.json"
    if council.exists():
        n["council"] = json.loads(council.read_text(encoding="utf-8"))
    briefs = sorted((ROOT / "outputs" / "ai_brief").glob("brief_*_record.json"))
    if briefs:
        n["brief"] = json.loads(briefs[-1].read_text(encoding="utf-8"))

    (OUT / "report_numbers.json").write_text(json.dumps(n, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: n[k] for k in ["moved_3y", "moved_share_3y", "moved_per_day_3y", "batch5plus_share_2024",
                                         "ride_down_2024", "move_up_2024", "moved_share_8am",
                                         "truck_km_per_day_2024_cap20", "vuln_count", "vuln_both_count"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
