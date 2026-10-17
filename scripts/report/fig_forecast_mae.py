"""필요 대수 예측 오차(MAE): 시험기간 전체 / 비 오는 날(≥1mm) × 경험 규칙·AI·AI+당일 날씨(상한).

원천: data/processed/forecast/q_metrics.csv(전체), q_metrics_segments.csv(구간). split == test.
MAE = 거점·일당 '아침 필요 대수(q)' 예측 오차 평균(대). 감소율 = (규칙 − 방법) / 규칙.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

FC = S.ROOT / "data" / "processed" / "forecast"
RAIN = "비 오는 날(≥1mm)"
METHODS = [("rule4w", "경험 규칙"), ("ai", "AI 예측"), ("ai_weather", "AI+당일 날씨\n(상한)")]
REF = {"전체": (3.238, 3.004, 2.706), "비": (3.889, 3.643, 2.884)}      # 지시서 참고 값(파일 값과 대조용)


def main() -> int:
    S.setup()
    q = pd.read_csv(FC / "q_metrics.csv", encoding="utf-8-sig")
    sg = pd.read_csv(FC / "q_metrics_segments.csv", encoding="utf-8-sig")
    q, sg = q[q["split"] == "test"].set_index("model"), sg[sg["split"] == "test"]
    groups = [("전체", {m: float(q.loc[m, "mae"]) for m, _ in METHODS}, int(q.loc["ai", "station_days"])),
              (RAIN, {m: float(sg[(sg["segment"] == RAIN) & (sg["model"] == m)]["mae"].iloc[0]) for m, _ in METHODS},
               int(sg[(sg["segment"] == RAIN) & (sg["model"] == "ai")]["station_days"].iloc[0]))]

    fig, ax = plt.subplots(figsize=(62 * S.MM, 46 * S.MM))
    fig.subplots_adjust(left=0.265, right=0.995, top=0.90, bottom=0.01)
    ax.set_xlim(0, 6.9)
    ax.set_ylim(0.35, 7.7)
    top_y, header_y = [6.4, 2.7], [7.25, 3.55]
    out = {"source": ["q_metrics.csv", "q_metrics_segments.csv"], "split": "test", "unit": "대(거점·일당 평균 절대오차)", "groups": {}}
    for (gname, mae, n), y0, hy, ref in zip(groups, top_y, header_y, REF.values()):
        ax.text(0, hy, "전체" if gname == "전체" else "비 오는 날 (≥1mm)", fontsize=S.FS_SMALL, fontweight="bold",
                color=S.INK2, va="center", ha="left")
        red = {m: (mae["rule4w"] - mae[m]) / mae["rule4w"] * 100 for m, _ in METHODS}
        for i, (m, _) in enumerate(METHODS):
            y, v = y0 - 0.9 * i, mae[m]
            if m == "ai_weather":
                ax.barh(y, v, height=0.7, color=S.GRID, edgecolor=S.CONTEXT, linewidth=0.8, linestyle=(0, (2.5, 1.5)))
            else:
                ax.barh(y, v, height=0.7, color=S.CONTEXT if m == "rule4w" else S.ACCENT, edgecolor="none")
            col = S.INK2 if m == "ai_weather" else (S.FOREST if m == "ai" else S.INK)
            t = ax.text(v + 0.08, y, f"{v:.2f}대", va="center", ha="left", fontsize=S.FS_LABEL, color=col,
                        fontweight="bold" if m == "ai" else "normal")
            if m == "ai":
                fig.canvas.draw()
                x1 = t.get_window_extent().transformed(ax.transData.inverted()).x1
                ax.text(x1 + 0.1, y, f"−{red[m]:.1f}%", va="center", ha="left", fontsize=7.5, color=S.ACCENT, fontweight="bold")
        out["groups"][gname] = {"station_days": n, "mae": {m: round(v, 4) for m, v in mae.items()},
                                "reduction_vs_rule_pct": {m: round(v, 2) for m, v in red.items() if m != "rule4w"},
                                "ref_given": dict(zip(["rule4w", "ai", "ai_weather"], ref)),
                                "ref_matches_file_3dp": [round(mae[m], 3) == r for (m, _), r in zip(METHODS, ref)]}
    ax.set_yticks([top_y[0] - 0.9 * i for i in range(3)] + [top_y[1] - 0.9 * i for i in range(3)])
    ax.set_yticklabels([n for _, n in METHODS] * 2, fontsize=7.5)
    ax.set_xticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=3)
    ax.set_title("필요 대수 예측 오차(MAE, 시험기간)", fontsize=S.FS_SMALL, loc="left", color=S.INK2, pad=4, x=-0.36)
    (S.FIG_DIR / "forecast_mae.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    print(S.save(fig, "forecast_mae"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
