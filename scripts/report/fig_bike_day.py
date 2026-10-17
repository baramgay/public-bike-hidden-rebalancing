"""자전거 4503번의 하루(2024-01-10 06시 ~ 01-11 10시): 자전거가 있던 곳의 고도를 시간순으로 그린다.

실선 = 이용 기록(사람이 탐), 가는 회색 = 거치 중, 점선 띠 = 반납~다음 대여 사이의 기록 없는 이동(정확한 시각은 모름)
입력: outputs/report_figures/example_bike_4503.json (trace_bike_chains 출력에서 추출)
"""
from __future__ import annotations

import json

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import style as S

W0, W1 = pd.Timestamp("2024-01-10 06:00"), pd.Timestamp("2024-01-11 10:00")


def main() -> None:
    S.setup()
    ex = json.loads((S.FIG_DIR / "example_bike_4503.json").read_text(encoding="utf-8"))
    trips = [t for t in ex["trips"] if W0 <= pd.Timestamp(t["start"]) <= W1]
    moves = [m for m in ex["unrecorded_moves"] if W0 <= pd.Timestamp(m["returned"]) <= W1]
    fig, ax = plt.subplots(figsize=(88 / 25.4, 50 / 25.4))
    prev = None
    for t in trips:
        s, e = pd.Timestamp(t["start"]), pd.Timestamp(t["end"])
        if prev is not None and prev["to"]["id"] == t["from"]["id"]:      # 같은 거점에 거치
            ax.plot([pd.Timestamp(prev["end"]), s], [t["from"]["elev_m"]] * 2, color=S.CONTEXT, lw=0.8)
        ax.plot([s, e], [t["from"]["elev_m"], t["to"]["elev_m"]], color=S.ACCENT, lw=2.2, solid_capstyle="round")
        prev = t
    for m in moves:                                   # 이동 시각은 모름 → 시간창 띠 + 세로 화살표(순간 이동처럼)
        r, n = pd.Timestamp(m["returned"]), pd.Timestamp(m["next_rental"])
        lo, hi = sorted([m["from"]["elev_m"], m["to"]["elev_m"]])
        ax.fill_between([r, n], lo, max(hi, lo + 2), color=S.MINT, alpha=0.18, lw=0)
        ax.plot([r, n], [m["from"]["elev_m"]] * 2, color=S.CONTEXT, lw=0.8, ls=(0, (2, 2)))
    night = moves[-1]
    r, n = pd.Timestamp(night["returned"]), pd.Timestamp(night["next_rental"])
    xa = r + (n - r) * 0.82
    ax.annotate("", xy=(xa, night["to"]["elev_m"]), xytext=(xa, night["from"]["elev_m"]),
                arrowprops=dict(arrowstyle="-|>", color=S.FOREST, lw=1.4, ls="--", mutation_scale=9))
    ax.text(r + (n - r) * 0.38, 64, f"기록 없는\n이동\n{night['dist_km']:.1f}km\n+{night['dh_m']:.0f}m",
            ha="center", va="center", fontsize=8, color=S.FOREST, fontweight="bold", linespacing=1.15)
    ax.text(r + pd.Timedelta(minutes=20), 11, "22:24 반납\n해발 23m", ha="left", va="center", fontsize=7.5, color=S.INK2)
    ax.text(n, night["to"]["elev_m"] + 4, "07:42 대여 · 해발 105m", ha="right", va="bottom", fontsize=7.5, color=S.INK2)
    n_rides = sum(pd.Timestamp(t["start"]).date() == pd.Timestamp("2024-01-10").date() for t in trips)
    ax.text(pd.Timestamp("2024-01-10 06:30"), 70, f"1월 10일\n이용 {n_rides}번", fontsize=S.FS_LABEL, color=S.ACCENT,
            fontweight="bold", va="center", linespacing=1.15)
    ax.set_xlim(W0, W1)
    ax.set_ylim(0, 122)
    ax.set_ylabel("자전거 위치 고도(m)", fontsize=7.5)
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[6, 12, 18, 0, 6]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H시"))
    ax.tick_params(labelsize=7.5)
    ax.grid(axis="y", color=S.GRID, lw=0.5)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    S.save(fig, "bike_day_4503")
    out = {"bike": ex["bike"], "rides_jan10": n_rides, "night_move": night,
           "window": [str(W0), str(W1)], "source": "example_bike_4503.json"}
    (S.FIG_DIR / "bike_day_4503.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
