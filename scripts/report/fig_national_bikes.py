"""시도별 공영자전거 대여 실적(2024): 전국 규모 설명용, 분석 사례 지역(경남, 창원 누비자)만 강조.

자료: 행정안전부 2025 행정안전통계연보('24.12.31 기준) 4-2-7-2 공영자전거 운영 현황(참고문헌 27).
값은 data/metadata/grok_national_bikeshare_open_data_20261018.md에 옮겨 적은 시도별 표이며, 합계가 연보 전국값과 일치하는지 실행 때 검사한다.
자전거 번호 공개 도시: 창원·김해(경남), 대전(같은 문서 '이용 건 이력에 자전거번호가 보인 곳').
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style as S  # noqa: E402

# 시도: (스테이션, 보유 대수, 대여 실적)
D = {"서울": (2777, 45958, 43884991), "부산": (16, 1135, 82190), "대구": (40, 324, 16464), "인천": (1, 104, 2190),
     "광주": (98, 704, 87037), "대전": (1280, 5500, 5747171), "울산": (2, 318, 22848), "세종": (704, 3485, 2582293),
     "경기": (22, 1058, 60671), "강원": (43, 308, 87626), "충북": (27, 67, 15324), "충남": (37, 772, 174691),
     "전북": (24, 616, 45021), "전남": (153, 1166, 290620), "경북": (193, 1938, 452655), "경남": (524, 6083, 4612154),
     "제주": (11, 36, 13158)}
TOTAL = (5952, 69572, 58177104)      # 연보 전국 합계
OPEN = {"대전": "대전 타슈", "경남": "창원 누비자·김해"}   # 기록용(번호 열 확인 도시가 있는 시도). 공개 범위 대표값으로 쓰지 않음
CASE = {"경남": "분석 사례(창원 누비자)"}
TOP = 6


def main() -> int:
    assert tuple(sum(v[i] for v in D.values()) for i in range(3)) == TOTAL, "시도 합계가 연보 전국값과 다름"
    S.setup()
    rows = sorted(D.items(), key=lambda kv: -kv[1][2])
    top, rest = rows[:TOP], rows[TOP:]
    items = [(k, v[2], k in CASE) for k, v in top] + [(f"그 외 {len(rest)}개 시도", sum(v[2] for _, v in rest), False)]
    fig, ax = plt.subplots(figsize=(88 * S.MM, 36 * S.MM))
    fig.subplots_adjust(left=0.2, right=0.83, top=0.99, bottom=0.02)
    ys = list(range(len(items)))[::-1]
    vmax = items[0][1] / 1e4
    for y, (name, v, hi) in zip(ys, items):
        ax.barh(y, v / 1e4, height=0.62, color=S.ACCENT if hi else S.CONTEXT, edgecolor="none")
        label = f"{v / 1e4:,.0f}만 건"
        ax.text(v / 1e4 + vmax * 0.015, y, label, va="center", ha="left", fontsize=7.5,
                color=S.FOREST if hi else S.INK2, fontweight="bold" if hi else "normal")
        if hi:
            ax.text(vmax * 0.37, y, CASE[name], va="center", ha="left", fontsize=7.5, color=S.ACCENT, clip_on=False)
    ax.set_yticks(ys)
    ax.set_yticklabels([n for n, _, _ in items], fontsize=7.5)
    for t, (_, _, hi) in zip(ax.get_yticklabels(), items):
        t.set_color(S.FOREST if hi else S.INK2)
        t.set_fontweight("bold" if hi else "normal")
    ax.set_xlim(0, vmax * 1.02)
    ax.set_xticks([])
    ax.tick_params(length=0, pad=2)
    for sp in ax.spines.values():
        sp.set_visible(False)
    share = sum(D[k][2] for k in OPEN) / TOTAL[2]
    out = {"source": "2025 행정안전통계연보 4-2-7-2(2024.12.31 기준)", "total": dict(zip(("stations", "bikes", "rentals"), TOTAL)),
           "open_regions": list(OPEN), "open_regions_rental_share": round(share, 4),
           "open_regions_bike_share": round(sum(D[k][1] for k in OPEN) / TOTAL[1], 4),
           "seoul_rental_share": round(D["서울"][2] / TOTAL[2], 4), "rows": [{"name": n, "rentals": v} for n, v, _ in items]}
    (S.FIG_DIR / "national_bikes.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(S.save(fig, "national_bikes"), out["open_regions_rental_share"], out["seoul_rental_share"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
