"""재배치를 하지 않으면: 재배치 없음 vs AI 예측(예산 1500)의 집단별 관측 대여 성공률 (시험기간).

결과 파일: results_v2.csv가 있으면 그것, 없으면 results_main.csv. 집단 열은 결과 파일의 `served_rate[...]`.
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
# (표시 이름, 결과 파일 열)
GROUPS = [("전체", "served_rate", None), ("고지대\n(상위 25%)", "served_rate[고지대(상위25%)]", "고지대(상위25%)"),
          ("취약 거점", "served_rate[취약]", "취약")]


def load_results() -> tuple[str, pd.DataFrame]:
    f = SIM / "results_v2.csv"
    if not f.exists():
        f = SIM / "results_main.csv"
    r = pd.read_csv(f, encoding="utf-8-sig")
    return f.name, r[r["split"] == "test"]


def main() -> int:
    S.setup()
    src, t = load_results()
    assert all(c in t.columns for _, c, _ in GROUPS), "결과 파일에 집단 열 없음"
    none = t[t["strategy"] == "none"].iloc[0]
    ai = t[(t["strategy"] == "ai") & (t["budget"] == BUDGET)].iloc[0]
    meta = SIM / f"meta_{src[len('results_'):-len('.csv')]}.json"
    n_g = json.loads(meta.read_text(encoding="utf-8")).get("groups", {}) if meta.exists() else {}

    fig, ax = plt.subplots(figsize=(62 * S.MM, 46 * S.MM))
    fig.subplots_adjust(left=0.255, right=0.995, top=0.895, bottom=0.01)
    ax.set_xlim(0, 128)
    ax.set_ylim(-0.5, 2.5)
    out = {"source_file": src, "split": "test", "ai_budget": BUDGET,
           "ai_moves_per_night": round(float(ai["moves_per_night"]), 1), "ai_truck_km_per_night": round(float(ai["truck_km_per_night"]), 1),
           "groups": {}}
    centers = [2, 1, 0]
    for c, (name, col, gkey) in zip(centers, GROUPS):
        v0, v1 = float(none[col]) * 100, float(ai[col]) * 100
        for y, v, color, is_ai in [(c + 0.21, v0, S.CONTEXT, False), (c - 0.21, v1, S.ACCENT, True)]:
            ax.barh(y, v, height=0.38, color=color, edgecolor="none")
            ax.text(v + 1.5, y, f"{v:.1f}%", va="center", ha="left", fontsize=S.FS_LABEL,
                    color=S.FOREST if is_ai else S.INK, fontweight="bold" if is_ai else "normal")
        if c == centers[0]:       # 첫 집단 막대 안에 직접 라벨(범례 대체)
            ax.text(2, c + 0.21, "재배치 없음", va="center", ha="left", fontsize=7.5, color=S.FOREST, fontweight="semibold")
            ax.text(2, c - 0.21, "AI 예측 (예산 1,500)", va="center", ha="left", fontsize=7.5, color="white", fontweight="bold")
        key = name.replace("\n", " ")
        out["groups"][key] = {"none_served_rate_pct": round(v0, 2), "ai_served_rate_pct": round(v1, 2), "gain_pp": round(v1 - v0, 2),
                              "stations": n_g.get(gkey)}
    ax.set_yticks(centers)
    ax.set_yticklabels([g[0] for g in GROUPS], fontsize=S.FS_SMALL)
    ax.set_xticks([])
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=3)
    ax.set_title("관측 대여 성공률(%)", fontsize=S.FS_SMALL, loc="left", color=S.INK2, pad=4, x=-0.25)
    (S.FIG_DIR / "notruck.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    print(S.save(fig, "notruck"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
