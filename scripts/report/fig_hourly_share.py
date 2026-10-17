"""시간대별: 그 시간 대여 중 '기록 없이 옮겨져 온 자전거'의 비율 (2023~2025 합계).

분자: 다른 거점에서 기록 없이 옮겨진 뒤 그 시간에 다시 대여된 자전거(핵심 무인 이동, 다음 대여 시각 기준)
분모: 그 시간의 전체 대여
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402


def main() -> int:
    S.setup()
    h = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "hourly_profile.csv")
    h = h[h["rentals"] >= 1000].copy()            # 01~03시(대여 거의 없음) 제외
    h["share"] = h["moved_before_rental_hour"] / h["rentals"]
    fig, ax = plt.subplots(figsize=(120 * S.MM, 46 * S.MM))
    peak = h["share"].idxmax()
    colors = [S.ACCENT if i == peak or h.loc[i, "hour"] in (7, 8) else S.LIGHT_ACCENT for i in h.index]
    ax.bar(h["hour"], h["share"] * 100, width=0.72, color=colors, edgecolor="none")
    for i in h.index:
        if h.loc[i, "hour"] in (8, 17, 12):
            ax.text(h.loc[i, "hour"], h.loc[i, "share"] * 100 + 0.6, f"{h.loc[i, 'share']*100:.0f}%",
                    ha="center", va="bottom", fontsize=S.FS_LABEL, color=S.FOREST, fontweight="bold")
    ax.set_xticks([0, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22])
    ax.set_xticklabels([f"{x}시" for x in [0, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]], fontsize=S.FS_SMALL)
    ax.set_yticks([0, 10, 20])
    ax.set_yticklabels(["0", "10", "20%"], fontsize=S.FS_SMALL)
    ax.set_ylim(0, 23)
    ax.grid(axis="y", color=S.GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines[["left"]].set_visible(False)
    ax.tick_params(axis="both", length=0)
    out = {"by_hour": {int(r.hour): round(float(r.share), 4) for r in h.itertuples()},
           "definition": "시간대 대여 중 기록 없이 옮겨져 온 자전거 비율, 2023~2025 합계"}
    (S.FIG_DIR / "hourly_share.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    S.save(fig, "hourly_moved_share")
    return 0


if __name__ == "__main__":
    sys.exit(main())
