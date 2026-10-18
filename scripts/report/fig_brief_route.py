"""운영자 브리핑 화면용 첫 구간 차량 경로 지도(2025-04-15 배치안, LangGraph 브리핑 기록의 first_segments[0]).

글자는 축척 막대만 넣고, 범례·설명은 보고서에서 직접 쓴다. 주변 거점은 맥락용 회색 점.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

BRIEF = sorted((S.ROOT / "outputs" / "ai_brief").glob("brief_*_record.json"))[-1]
W, H = 50, 30   # mm
MAP_BG = "#EEF5F2"   # 보고서 화면 상자와 같은 색(build_deck.js의 지도 배경)


def main() -> int:
    S.setup()
    rec = json.loads(BRIEF.read_text(encoding="utf-8"))
    run = rec["facts"]["first_segments"][0]
    st = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "stations.csv", encoding="utf-8-sig")
    st = st.sort_values("year").drop_duplicates("station_id", keep="last")
    by_name = st.drop_duplicates("name", keep="last").set_index("name")
    miss = [s["station"] for s in run["stops"] if s["station"] not in by_name.index]
    assert not miss, f"좌표 없는 정차 거점: {miss}"
    lat0 = 35.23
    xy = lambda lat, lon: ((lon - 128.65) * 111.32 * np.cos(np.radians(lat0)), (lat - lat0) * 110.57)
    pts = np.array([xy(by_name.loc[s["station"], "lat"], by_name.loc[s["station"], "lon"]) for s in run["stops"]])

    fig = plt.figure(figsize=(W * S.MM, H * S.MM), facecolor=MAP_BG)   # 축을 끄면 축 배경이 사라지므로 그림 배경에 색을 준다
    ax = fig.add_axes([0, 0, 1, 1])
    cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
    span_x = max(np.ptp(pts[:, 0]) * 1.35, 1.2)
    span_y = span_x * H / W
    if np.ptp(pts[:, 1]) * 1.3 > span_y:
        span_y = np.ptp(pts[:, 1]) * 1.3
        span_x = span_y * W / H
    ax.set_xlim(cx - span_x / 2, cx + span_x / 2)
    ax.set_ylim(cy - span_y / 2, cy + span_y / 2)
    ctx = np.array([xy(a, b) for a, b in zip(st["lat"], st["lon"])])
    ax.scatter(ctx[:, 0], ctx[:, 1], s=5, color="#C9D3CE", lw=0, zorder=1)
    ax.plot(pts[:, 0], pts[:, 1], color=S.FOREST, lw=1.1, alpha=0.85, zorder=2, solid_joinstyle="round")
    for a, b in zip(pts[:-1], pts[1:]):           # 진행 방향 화살표(구간 중간)
        if np.hypot(*(b - a)) > 0.08:
            m = (a + b) / 2
            ax.annotate("", xy=m + (b - a) * 0.06, xytext=m - (b - a) * 0.06,
                        arrowprops=dict(arrowstyle="-|>", color=S.FOREST, lw=0, mutation_scale=6), zorder=3)
    for (x, y), s in zip(pts, run["stops"]):
        size = 10 + 2.2 * s["bikes"]
        if s["action"] == "수거":
            ax.scatter(x, y, s=size, facecolor="white", edgecolor=S.CONTEXT, lw=1.1, zorder=4)
        else:
            ax.scatter(x, y, s=size, facecolor=S.ACCENT, edgecolor="white", lw=0.8, zorder=5)
    # 출발 표시(굵은 테두리)
    ax.scatter(*pts[0], s=46, facecolor="none", edgecolor=S.FOREST, lw=1.2, zorder=6)
    # 축척 500m
    x0, y0 = ax.get_xlim()[0] + span_x * 0.05, ax.get_ylim()[0] + span_y * 0.08
    ax.plot([x0, x0 + 0.5], [y0, y0], color=S.INK2, lw=1.2, solid_capstyle="butt", zorder=6)
    ax.text(x0 + 0.25, y0 + span_y * 0.035, "500m", ha="center", va="bottom", fontsize=7.5, color=S.INK2, zorder=6)
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")
    out = {"brief": BRIEF.name, "run_km": run["km"], "stops": len(run["stops"]),
           "pickups": sum(s["action"] == "수거" for s in run["stops"]), "drops": sum(s["action"] == "배치" for s in run["stops"]),
           "unique_stations": len({s["station"] for s in run["stops"]})}
    (S.FIG_DIR / "brief_route.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(S.save(fig, "brief_route"), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
