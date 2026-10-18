"""취약 거점 형평성: 예산 1500에서 경험 규칙 · AI 예측 · AI+취약 보장(거점당 2대 보장) 비교 (시험기간).

(a) 취약 거점 대여 성공률(%), (b) 취약 거점 빈 시간 = 05~24시 중 재고 0 시간(거점·일 평균, 시간).
결과 파일: results_v2.csv가 있으면 그것, 없으면 results_main.csv. 열은 결과 파일의 `[취약]` 집단 열을 그대로 사용.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

SIM = S.ROOT / "data" / "processed" / "rebalancing_sim"
BUDGET = 1500
G = "취약"
STRATS = [("rule4w", "경험 규칙", S.CONTEXT), ("ai", "AI 예측", S.ACCENT), ("ai_fair", "AI+취약 보장", S.FOREST)]


def load_results() -> tuple[str, pd.DataFrame]:
    f = SIM / "results_v2.csv"
    if not f.exists():
        f = SIM / "results_main.csv"
    r = pd.read_csv(f, encoding="utf-8-sig")
    return f.name, r[r["split"] == "test"]


def main() -> int:
    S.setup()
    src, t = load_results()
    need = [f"served_rate[{G}]", f"zero_hours_per_station_day[{G}]", "served_rate", "moves_per_night"]
    assert all(c in t.columns for c in need), f"결과 파일에 열 없음: {[c for c in need if c not in t.columns]}"
    rows = {s: t[(t["strategy"] == s) & (t["budget"] == BUDGET)].iloc[0] for s, _, _ in STRATS}
    sr = {s: float(r[f"served_rate[{G}]"]) * 100 for s, r in rows.items()}
    zh = {s: float(r[f"zero_hours_per_station_day[{G}]"]) for s, r in rows.items()}
    meta = SIM / f"meta_{src[len('results_'):-len('.csv')]}.json"
    n_g = json.loads(meta.read_text(encoding="utf-8"))["groups"].get(G) if meta.exists() else None

    fig, axes = plt.subplots(1, 2, figsize=(84 * S.MM, 55 * S.MM), sharey=True)
    fig.subplots_adjust(left=0.215, right=0.995, top=0.795, bottom=0.185, wspace=0.12)
    ys = [2, 1, 0]
    for ax, vals, title, xmax, fmt in [(axes[0], sr, "취약 거점\n대여 성공률(%)", 134, "{:.1f}%"),
                                       (axes[1], zh, "취약 거점 빈 시간\n(시간/거점·일)", 2.25, "{:.2f}")]:
        ax.set_xlim(0, xmax)
        ax.set_ylim(-0.55, 2.55)
        for y, (s, name, c) in zip(ys, STRATS):
            ax.barh(y, vals[s], height=0.62, color=c, edgecolor="none")
            t_ = ax.text(vals[s] + xmax * 0.02, y, fmt.format(vals[s]), va="center", ha="left", fontsize=S.FS_LABEL,
                         color=S.FOREST if s == "ai_fair" else S.INK, fontweight="bold" if s == "ai_fair" else "normal")
            if ax is axes[1] and s == "ai_fair":     # 빈 시간 변화율(AI 대비)
                fig.canvas.draw()
                x1 = t_.get_window_extent().transformed(ax.transData.inverted()).x1
                ax.text(x1 + xmax * 0.02, y, f"{(vals[s] / vals['ai'] - 1) * 100:.0f}%".replace("-", "−"), va="center", ha="left",
                        fontsize=7.5, color=S.ACCENT, fontweight="bold")
        ax.set_xticks([])
        ax.spines[["left", "bottom"]].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=3)
        ax.set_title(title, fontsize=S.FS_SMALL, loc="left", color=S.INK2, pad=4, linespacing=1.15)
    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([n for _, n, _ in STRATS], fontsize=S.FS_SMALL)
    cost = (float(rows["ai_fair"]["served_rate"]) - float(rows["ai"]["served_rate"])) * 100
    red = (zh["ai_fair"] / zh["ai"] - 1) * 100
    fig.text(0.0, 0.0, (f"빈 시간 {red:.0f}%: AI 예측 대비\n"
                        f"전체 대여 성공률 변화(AI+취약 보장 − AI 예측): {cost:+.3f}%p").replace("-", "−"),
             fontsize=7.5, color=S.INK2, va="bottom", ha="left", linespacing=1.3)

    out = {"source_file": src, "split": "test", "budget": BUDGET, "group": G, "group_stations": n_g,
           "definition": {"served_rate": "집단 거점의 대여 성공률(서비스된 대여 / 수요), 시험기간 합계",
                          "zero_hours": "05~24시(19시간) 중 재고 0이었던 시간, 거점·일당 평균(시간). 시험기간 매일 '직전 28일 활동 있음'(운영센터 제외)이던 안정 거점만 평균. 성공률은 집단 전체 거점 기준이라 모수가 다름"},
           "strategies": {}}
    for s, name, _ in STRATS:
        r = rows[s]
        out["strategies"][s] = {"label": name, "moves_per_night": round(float(r["moves_per_night"]), 1),
                                "vulnerable_served_rate_pct": round(sr[s], 2), "vulnerable_zero_hours": round(zh[s], 3),
                                "overall_served_rate_pct": round(float(r["served_rate"]) * 100, 2)}
        for extra in ("그외(비취약)", "고지대(상위25%)"):
            if f"served_rate[{extra}]" in t.columns:
                out["strategies"][s][f"{extra}_served_rate_pct"] = round(float(r[f"served_rate[{extra}]"]) * 100, 2)
                out["strategies"][s][f"{extra}_zero_hours"] = round(float(r[f"zero_hours_per_station_day[{extra}]"]), 3)
    out["overall_cost_ai_fair_minus_ai_pp"] = round(cost, 3)
    out["overall_cost_ai_fair_minus_rule_pp"] = round((float(rows["ai_fair"]["served_rate"]) - float(rows["rule4w"]["served_rate"])) * 100, 3)
    out["vulnerable_gain_ai_fair_vs_ai"] = {"served_rate_pp": round(sr["ai_fair"] - sr["ai"], 3),
                                            "zero_hours_pct": round((zh["ai_fair"] / zh["ai"] - 1) * 100, 1)}
    out["vulnerable_gain_ai_fair_vs_rule"] = {"served_rate_pp": round(sr["ai_fair"] - sr["rule4w"], 3),
                                              "zero_hours_pct": round((zh["ai_fair"] / zh["rule4w"] - 1) * 100, 1)}
    (S.FIG_DIR / "equity.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    print(S.save(fig, "equity"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
