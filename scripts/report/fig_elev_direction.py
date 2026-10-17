"""고도 방향: 사람이 탄 이동 vs 기록 없는 이동의 내리막·평지·오르막 비율 (2024, 100% 가로 누적막대).

자료: elevation_flows.csv (trace_bike_chains.py의 고도 집계). 거점 고도차가 -5m 미만이면 내리막, +5m 초과면 오르막,
그 사이는 평지(= 1 - 내리막 - 오르막). 기록 없는 이동은 재배치 차량·정비가 섞인 추정치.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

YEAR = 2024
THRESHOLD_M = 5
W_MM, H_MM = 88, 40
X0, BAR_W = 22.0, 64.0          # 막대 시작·길이(mm)
MIN_LABEL_SHARE = 0.10          # 이보다 작은 조각은 막대 안 라벨 생략(막대 아래에 따로 표기)
ROWS = [("rental_trip", "사람이 탄 이동", 29.5), ("unrecorded_move", "기록 없는 이동", 16.5)]
BAR_H = 7.0
# 내리막 연한 청록 / 평지 옅은 회색 / 오르막 진한 청록
COLORS = {"down": S.RAMP[2], "flat": S.GRID, "up": S.ACCENT}
LABELS = {"down": "내리막", "flat": "평지", "up": "오르막"}
TXT = {"down": S.INK, "flat": S.INK2, "up": "#FFFFFF"}


def main() -> int:
    S.setup()
    e = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "elevation_flows.csv", encoding="utf-8-sig")
    e = e[e["year"] == YEAR].set_index("flow")
    fig = plt.figure(figsize=(W_MM * S.MM, H_MM * S.MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W_MM)
    ax.set_ylim(0, H_MM)
    ax.axis("off")

    out = {"year": YEAR, "threshold_m": THRESHOLD_M,
           "definition": f"출발·도착 거점 고도차(도착-출발) -{THRESHOLD_M}m 미만 내리막, +{THRESHOLD_M}m 초과 오르막, 그 사이 평지(=1-내리막-오르막)",
           "dem": "Copernicus GLO-30 DSM, 거점 주변 3x3 격자 최솟값(지면 근사)", "rows": {}}
    for flow, name, yc in ROWS:
        r = e.loc[flow]
        sh = {"down": float(r["share_down"]), "up": float(r["share_up"])}
        sh["flat"] = 1 - sh["down"] - sh["up"]
        out["rows"][flow] = {"name": name, "n": int(r["n"]), **{k: round(v, 4) for k, v in sh.items()}}
        left = X0
        for k in ("down", "flat", "up"):
            w = sh[k] * BAR_W
            ax.barh(yc, w, left=left, height=BAR_H, color=COLORS[k], edgecolor="white", linewidth=0.8)
            cx = left + w / 2
            if sh[k] >= MIN_LABEL_SHARE:
                ax.text(cx, yc, f"{sh[k]*100:.1f}%", ha="center", va="center",
                        fontsize=S.FS_SMALL if w >= 11 else 7.5,   # 좁은 조각은 글자를 줄여 조각 안에 맞춤
                        color=TXT[k], fontweight="bold")
            else:                                  # 작은 조각: 막대 아래 왼쪽 끝에 맞춰 표기
                ax.text(left, yc - BAR_H / 2 - 1.2, f"{LABELS[k]} {sh[k]*100:.1f}%", ha="left", va="top",
                        fontsize=7.5, color=S.INK2)
            if flow == ROWS[0][0]:                 # 범주 이름은 위 막대 조각 바로 위에 직접 표기
                ax.text(cx, yc + BAR_H / 2 + 1.2, LABELS[k], ha="center", va="bottom", fontsize=S.FS_SMALL,
                        color=S.FOREST if k == "up" else S.INK2, fontweight="bold" if k == "up" else "normal")
            left += w
        strong = flow == "unrecorded_move"
        ax.text(X0 - 2.0, yc + 1.4, name, ha="right", va="center", fontsize=S.FS_SMALL,
                color=S.FOREST if strong else S.INK, fontweight="bold")
        ax.text(X0 - 2.0, yc - 2.3, f"n={int(r['n']):,}", ha="right", va="center", fontsize=7.5, color=S.INK2)
    ax.text(0, 1.2, f"{YEAR}년 · 평지는 출발·도착 거점 고도차 {THRESHOLD_M}m 이내", ha="left", va="bottom",
            fontsize=7.5, color=S.MUTED)

    (S.FIG_DIR / "elev_direction.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    S.save(fig, "elev_direction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
