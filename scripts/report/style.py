"""보고서 그림 공통 양식: A4 인쇄 기준 글꼴·색·크기.

색(사용자 지시 2026-10-17: 주황 대신 숲과나눔·한겨레 계열, `design/sol/STYLE_UPDATE_20261017.md`)
- 제목·핵심 숫자: FOREST, 본문 잉크: INK
- 데이터 주 강조(트럭·재배치·AI 결과): ACCENT. 브랜드 청록 #137F7B는 채도 0.089로 차트에서 회색처럼 읽혀
  (dataviz 검증 chroma floor FAIL) 데이터 표식에는 #00897B를 쓰고 #137F7B는 도형·글자에 쓴다
- 맥락·비교 기준: CONTEXT(회색, 의도적 무채색) — 강조색 대 회색 쌍은 색각 이상 ΔE 12.3, 정상 17.7로 통과
- 두 번째 강조가 필요하면 FOREST + 선 모양(점선 등)·직접 라벨을 함께 쓴다(색만으로 구분하지 않음)
글꼴: 최신 사용자 확정 Pretendard 통일(`docs/codex_support/2026-10-17_폰트_사전점검.md` U20). 바꿀 때는 FONT 한 줄
"""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "outputs" / "report_figures"
FONT_DIRS = [Path(r"C:\Windows\Fonts"), Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"]
FONT = "Pretendard"
FONT_FILES = ("Pretendard-Regular.ttf", "Pretendard-Medium.ttf", "Pretendard-SemiBold.ttf",
              "Pretendard-Bold.ttf", "Pretendard-ExtraBold.ttf")

FOREST = "#183F35"
TEAL_BRAND = "#137F7B"
ACCENT = "#00897B"
MINT = "#00B8B4"
GREEN = "#437042"
SAGE = "#B8CBBF"
INK = "#26342E"
INK2 = "#4F5D57"
MUTED = "#8C9A93"
CONTEXT = "#9AA5AD"
GRID = "#E3E8E5"
PAPER = "#FFFFFF"
BG = "#F7F8F4"
SEA = "#DCE9EA"
# 순차 척도(청록 → 숲색 한 계열, 밝음→어두움)
RAMP = ["#E6F2EF", "#BFDDD6", "#8CC3B8", "#4FA396", "#00897B", "#0B6B61", "#183F35"]
LIGHT_ACCENT = "#BFDDD6"

MM = 1 / 25.4
# A4 인쇄 크기 기준 글자(pt)
FS_LABEL = 9.0
FS_SMALL = 8.5
FS_TITLE = 10.0


def setup() -> None:
    for name in FONT_FILES:
        for d in FONT_DIRS:
            if (d / name).exists():
                font_manager.fontManager.addfont(str(d / name))
                break
    mpl.rcParams.update({
        "font.family": FONT,
        "font.size": FS_LABEL,
        "axes.edgecolor": MUTED,
        "axes.labelcolor": INK2,
        "axes.titlecolor": INK,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "text.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.unicode_minus": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "savefig.dpi": 600,
        "figure.dpi": 150,
    })
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def save(fig, name: str) -> list[Path]:
    paths = []
    for ext in ("png", "svg"):
        p = FIG_DIR / f"{name}.{ext}"
        fig.savefig(p, bbox_inches="tight", pad_inches=0.02, facecolor=fig.get_facecolor())
        paths.append(p)
    return paths
