"""대표 지도: 창원 지형 음영 위 거점별 '트럭 의존도'(2024).

트럭 의존도 = 다른 거점에서 기록 없이 옮겨져 와 이 거점에서 대여된 자전거 / 이 거점 대여 (data/metadata/bike_chains.md)
각주(자료·정의)는 PPTX 캡션으로 넣는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import FancyBboxPatch
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

LON0, LON1, LAT0, LAT1 = 128.475, 128.835, 35.078, 35.385
WIDTH_MM = 118
MIN_RENTALS = 365
LABELS = {  # 거점번호: (표시 이름, 글자 위치 오프셋 경도, 위도, 정렬)
    159: ("성주 유니온빌리지", 0.030, -0.010, "left"),
    162: ("창원중앙역", 0.030, 0.034, "left"),
    377: ("자은에일린의 뜰", 0.022, -0.030, "left"),
    346: ("감계푸르지오", 0.040, 0.024, "left"),
    123: ("상남오거리", -0.045, -0.060, "right"),
}
DISTRICTS = {"의창구": (128.71, 35.36), "성산구": (128.775, 35.245), "마산회원구": (128.53, 35.285),
             "마산합포구": (128.515, 35.205), "진해구": (128.805, 35.097)}


def hillshade(z: np.ndarray, dx: float, dy: float, az: float = 315, alt: float = 45) -> np.ndarray:
    gy, gx = np.gradient(z, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    hs = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.clip(hs, 0, 1)


def main() -> int:
    S.setup()
    dem_path = S.ROOT / "data" / "raw" / "elevation" / "Copernicus_DSM_COG_10_N35_00_E128_00_DEM.tif"
    with rasterio.open(dem_path) as r:
        win = from_bounds(LON0, LAT0, LON1, LAT1, r.transform)
        z = r.read(1, window=win).astype(float)
        tr = r.window_transform(win)
    lat_mid = (LAT0 + LAT1) / 2
    dx = abs(tr.a) * 111_320 * np.cos(np.radians(lat_mid))
    dy = abs(tr.e) * 110_570
    hs = hillshade(z, dx, dy)
    sea = z <= 0.5
    land = np.clip(0.95 + 0.16 * (hs - 0.71), 0.78, 1.0)
    rgb = np.dstack([land * 0.985, land * 0.975, land * 0.955])
    rgb[sea] = [int(S.SEA[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    f = pd.read_csv(S.ROOT / "data" / "processed" / "bike_chains" / "station_year_flows.csv")
    f["is_ops_center"] = f["is_ops_center"].astype(str).eq("True")
    f = f[(f["year"] == 2024) & ~f["is_ops_center"] & f["lat"].notna()].copy()
    f["dep"] = f["moved_in"] / f["rentals"].where(f["rentals"] > 0)
    main_ = f[f["rentals"] >= MIN_RENTALS].sort_values("dep")
    minor = f[f["rentals"] < MIN_RENTALS]

    fig_w = WIDTH_MM * S.MM
    aspect = 110.57 / (111.32 * np.cos(np.radians(lat_mid)))
    fig_h = fig_w * (LAT1 - LAT0) * aspect / (LON1 - LON0)
    fig = plt.figure(figsize=(fig_w, fig_h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(rgb, extent=(LON0, LON1, LAT0, LAT1), origin="upper", interpolation="bilinear", zorder=0)
    ax.set_aspect(aspect)
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_axis_off()

    for name, (x, y) in DISTRICTS.items():
        ax.text(x, y, name, fontsize=S.FS_SMALL, color=S.MUTED, ha="center", va="center", zorder=1)

    bounds = [0, 0.05, 0.10, 0.20, 0.35, 0.50, 1.0]
    cmap = ListedColormap(S.RAMP[1:])
    norm = BoundaryNorm(bounds, cmap.N)
    ax.scatter(minor["lon"], minor["lat"], s=3, color=S.CONTEXT, linewidths=0, alpha=0.7, zorder=2)
    size = 4 + 26 * np.sqrt(main_["rentals"] / main_["rentals"].max())
    sc = ax.scatter(main_["lon"], main_["lat"], s=size, c=main_["dep"], cmap=cmap, norm=norm,
                    edgecolors="white", linewidths=0.3, zorder=3)

    for sid, (label, ox, oy, ha) in LABELS.items():
        r = f[f["station_id"] == sid]
        if r.empty:
            continue
        r = r.iloc[0]
        txt = f"{label}\n{r['dep']*100:.0f}% · 해발 {r['elev_m']:.0f}m"
        ax.annotate(txt, xy=(r["lon"], r["lat"]), xytext=(r["lon"] + ox, r["lat"] + oy),
                    fontsize=S.FS_LABEL, color=S.INK, ha=ha, va="center", linespacing=1.15,
                    arrowprops=dict(arrowstyle="-", color=S.INK2, lw=0.5, shrinkA=0, shrinkB=1.5), zorder=4)

    # 범례: 흰 상자(지도 축 안, 낮은 zorder) 위에 색 막대 축
    ax.add_patch(FancyBboxPatch((0.015, 0.015), 0.6, 0.12, boxstyle="round,pad=0,rounding_size=0.01",
                                transform=ax.transAxes, facecolor="white", edgecolor="none", alpha=0.92, zorder=5))
    cax = fig.add_axes([0.035, 0.038, 0.53, 0.024])
    cax.set_zorder(10)
    cb = fig.colorbar(sc, cax=cax, orientation="horizontal", ticks=bounds)
    cb.ax.set_xticklabels(["0", "5", "10", "20", "35", "50", "100%"], fontsize=S.FS_SMALL)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, pad=1.5)
    cax.set_title("대여 중 기록 없이 옮겨져 온 자전거 비율", fontsize=S.FS_LABEL, loc="left", pad=3, color=S.INK)
    paths = S.save(fig, "map_truck_dependency_2024")
    print([str(p) for p in paths], round(fig_w / S.MM), round(fig_h / S.MM))
    return 0


if __name__ == "__main__":
    sys.exit(main())
