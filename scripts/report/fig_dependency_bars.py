"""트럭 의존도 막대: 거점 고도 사분위별, 생활 접근성(복합 취약)별 (2024, 대여 합 기준 비율).

의존도 = 집단 내 '다른 곳에서 옮겨져 와 대여된 자전거' 합 / 집단 대여 합.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

MIN_RENTALS = 365


def main() -> int:
    S.setup()
    f = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "station_year_flows.csv")
    f["is_ops_center"] = f["is_ops_center"].astype(str).eq("True")
    f = f[(f["year"] == 2024) & ~f["is_ops_center"] & (f["rentals"] >= MIN_RENTALS) & f["elev_m"].notna()].copy()
    q, edges = pd.qcut(f["elev_m"], 4, labels=False, retbins=True)
    f["elev_q"] = q
    rows = []
    names = [f"저지대\n{edges[1]:.0f}m 미만", f"{edges[1]:.0f}~{edges[2]:.0f}m",
             f"{edges[2]:.0f}~{edges[3]:.0f}m", f"고지대\n{edges[3]:.0f}m 이상"]
    for k in range(4):
        g = f[f["elev_q"] == k]
        rows.append(("고도", names[k], g["moved_in"].sum() / g["rentals"].sum(), len(g), k == 3))
    v = pd.read_csv(S.ROOT / "data" / "processed" / "accessibility_scenarios" / "station_vulnerability.csv")
    v = v[v["classified"].astype(str) == "True"][["station_id", "vulnerable_both"]]
    m = f.merge(v, on="station_id", how="inner")
    for flag, name in [("False", "그 외"), ("True", "버스·병원·약국\n모두 먼 거점")]:
        g = m[m["vulnerable_both"].astype(str) == flag]
        rows.append(("접근성", name, g["moved_in"].sum() / g["rentals"].sum(), len(g), flag == "True"))

    fig, axes = plt.subplots(2, 1, figsize=(60 * S.MM, 74 * S.MM), gridspec_kw={"height_ratios": [4, 2.3], "hspace": 0.55})
    for ax, grp, title in [(axes[0], "고도", "거점 고도별"), (axes[1], "접근성", "생활 접근성별")]:
        sub = [r for r in rows if r[0] == grp]
        ys = range(len(sub))[::-1]
        for y, (_, name, val, n, hi) in zip(ys, sub):
            ax.barh(y, val * 100, height=0.62, color=S.ACCENT if hi else S.LIGHT_ACCENT, edgecolor="none")
            ax.text(val * 100 + 1, y, f"{val*100:.1f}%", va="center", ha="left", fontsize=S.FS_LABEL,
                    color=S.FOREST if hi else S.INK, fontweight="bold" if hi else "normal")
        ax.set_yticks(list(ys))
        ax.set_yticklabels([r[1] for r in sub], fontsize=S.FS_SMALL)
        ax.set_xlim(0, 40)
        ax.set_xticks([])
        ax.spines[["left", "bottom"]].set_visible(False)
        ax.tick_params(axis="y", length=0, pad=3)
        ax.set_title(title, fontsize=S.FS_LABEL, loc="left", color=S.INK2, pad=4)
    out = {"rows": [{"group": r[0], "name": r[1].replace("\n", " "), "dependency": round(r[2], 4), "stations": r[3]} for r in rows],
           "elev_quartile_edges_m": [round(e, 1) for e in edges], "min_rentals": MIN_RENTALS}
    (S.FIG_DIR / "dependency_bars.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    S.save(fig, "dependency_bars_2024")
    return 0


if __name__ == "__main__":
    sys.exit(main())
