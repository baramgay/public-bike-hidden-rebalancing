"""기록 없는 이동의 출발 구 × 도착 구 행렬 (2024, 전체 대비 %).

자료: district_move_matrix.csv (핵심 기록 없는 이동 건수). 대각선 = 같은 구 안 이동.
색: 순차 RAMP, 대각선 칸 하나가 57%로 나머지를 압도하므로 제곱근 척도(PowerNorm 0.5)로 작은 칸도 구분.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from matplotlib.patches import Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

YEAR = 2024
DISTRICTS = ["의창구", "성산구", "마산합포구", "마산회원구", "진해구"]
SHORT = ["의창", "성산", "마산\n합포", "마산\n회원", "진해"]
W_MM, H_MM = 62, 56
GX0, GX1 = 12.5, 61.5            # 격자 좌우(mm)
GY0, GY1 = 10.0, 46.5             # 격자 하단·상단(mm)


def main() -> int:
    S.setup()
    m = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "district_move_matrix.csv", encoding="utf-8-sig")
    m = m[m["year"] == YEAR]
    ok = m["from_district"].isin(DISTRICTS) & m["to_district"].isin(DISTRICTS)
    excluded = int(m.loc[~ok, "n"].sum())
    mat = m[ok].pivot_table(index="from_district", columns="to_district", values="n", aggfunc="sum", fill_value=0)
    mat = mat.reindex(index=DISTRICTS, columns=DISTRICTS, fill_value=0)
    total = int(mat.values.sum())
    pct = mat.values / total * 100
    diag_n = int(np.trace(mat.values))
    diag_pct = diag_n / total * 100

    cmap = LinearSegmentedColormap.from_list("ramp", S.RAMP)
    norm = PowerNorm(0.5, vmin=0, vmax=pct.max())
    fig = plt.figure(figsize=(W_MM * S.MM, H_MM * S.MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W_MM)
    ax.set_ylim(0, H_MM)
    ax.axis("off")
    cw, ch = (GX1 - GX0) / 5, (GY1 - GY0) / 5
    for i in range(5):                                  # i: 출발(행), j: 도착(열)
        for j in range(5):
            x, y = GX0 + j * cw, GY1 - (i + 1) * ch
            ax.add_patch(Rectangle((x, y), cw, ch, facecolor=cmap(norm(pct[i, j])), edgecolor="white", linewidth=1.0))
            v = pct[i, j]
            txt = f"{v:.1f}%" if round(v, 1) > 0 else "<0.1%"
            ax.text(x + cw / 2, y + ch / 2, txt, ha="center", va="center", fontsize=8 if round(v, 1) > 0 else 7.5,
                    color="#FFFFFF" if norm(v) > 0.5 else S.INK, fontweight="bold" if i == j else "normal")
    for i in range(5):                                  # 대각선(같은 구 안) 테두리
        ax.add_patch(Rectangle((GX0 + i * cw, GY1 - (i + 1) * ch), cw, ch, facecolor="none",
                               edgecolor=S.FOREST, linewidth=1.0))
    for k, s in enumerate(SHORT):
        ax.text(GX0 + (k + 0.5) * cw, GY1 + 1.0, s, ha="center", va="bottom", fontsize=7.5, color=S.INK2, linespacing=1.0)
        ax.text(GX0 - 1.2, GY1 - (k + 0.5) * ch, s, ha="right", va="center", fontsize=7.5,
                color=S.INK2, linespacing=1.0)
    ax.text(GX0 + 2.5 * cw, H_MM - 0.3, "도착 구", ha="center", va="top", fontsize=S.FS_SMALL, color=S.INK, fontweight="bold")
    ax.text(1.5, GY1 - 2.5 * ch, "출발 구", ha="center", va="center", fontsize=S.FS_SMALL, color=S.INK,
            fontweight="bold", rotation=90)
    ax.text(0, 5.3, f"테두리 칸 = 같은 구 안 이동, 합계 {diag_pct:.1f}%", ha="left", va="bottom", fontsize=7.5, color=S.INK2)
    ax.text(0, 1.0, f"{YEAR}년 · 칸 값은 전체 대비 % · 색 농도는 제곱근 척도", ha="left", va="bottom", fontsize=7.5, color=S.INK2)

    out = {"year": YEAR, "order": DISTRICTS, "total_n": total, "excluded_unmapped_n": excluded,
           "n": mat.values.tolist(), "pct_of_total": np.round(pct, 3).tolist(),
           "diagonal_n": diag_n, "diagonal_pct": round(diag_pct, 2),
           "color_scale": "PowerNorm gamma=0.5 (제곱근), RAMP 순차"}
    (S.FIG_DIR / "district_matrix.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    S.save(fig, "district_matrix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
