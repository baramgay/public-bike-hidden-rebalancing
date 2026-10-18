"""정책 효율 곡선: 밤당 실제 이동 대수(평균) 대비 관측 대여 성공률 (시험기간, 예산 250~2500).

결과 파일: results_v2.csv가 있으면 그것, 없으면 results_main.csv. split == test.
'같은 성공률에 필요한 이동 대수' = 경험 규칙의 예산 1500 성공률을 AI 곡선이 처음 넘는 구간을 선형 보간.
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
# (전략, 라벨, 색, 선모양, 굵기, 글자색, 굵게)
LINES = [("oracle", "완벽 예측(상한)", S.CONTEXT, (0, (1.2, 1.8)), 1.1, S.INK2, False),
         ("ai_weather", "AI+당일 날씨(상한)", S.MINT, (0, (3.5, 2)), 1.4, S.INK2, False),
         ("ai", "AI 예측", S.ACCENT, "-", 1.9, S.FOREST, True),
         ("rule4w", "경험 규칙", S.CONTEXT, "-", 1.5, S.INK2, False)]


def load_results() -> tuple[str, pd.DataFrame]:
    f = SIM / "results_v2.csv"
    if not f.exists():
        f = SIM / "results_main.csv"
    r = pd.read_csv(f, encoding="utf-8-sig")
    return f.name, r[r["split"] == "test"]


def interp_moves(curve: pd.DataFrame, target: float) -> float:
    """곡선(이동 대수 오름차순)이 target 성공률을 처음 넘는 지점의 이동 대수(선형 보간)."""
    c = curve.sort_values("moves_per_night")
    for (x0, y0), (x1, y1) in zip(c[["moves_per_night", "served_rate"]].values[:-1], c[["moves_per_night", "served_rate"]].values[1:]):
        if y0 < target <= y1:
            return float(x0 + (target - y0) / (y1 - y0) * (x1 - x0))
    return float("nan")


def spread(ys: list[float], gap: float) -> list[float]:
    """위에서 아래로 최소 간격 gap을 지키도록 라벨 y를 조정(입력은 내림차순)."""
    out = [ys[0]]
    for y in ys[1:]:
        out.append(min(y, out[-1] - gap))
    return out


def draw(ax, t: pd.DataFrame, lw_scale: float = 1.0) -> None:
    for s, _, c, ls, lw, _, _ in LINES:
        d = t[t["strategy"] == s].sort_values("budget")
        ax.plot(d["moves_per_night"], d["served_rate"] * 100, color=c, ls=ls, lw=lw * lw_scale, zorder=3, solid_capstyle="round")
        p = d[d["budget"] == BUDGET].iloc[0]
        ax.plot(p["moves_per_night"], p["served_rate"] * 100, "o", ms=3.6 if s == "ai" else 3.0, color=c, mec="white", mew=0.6, zorder=5,
                clip_on=False)


def main() -> int:
    S.setup()
    src, t = load_results()
    none = t[t["strategy"] == "none"].iloc[0]
    get = lambda s: t[(t["strategy"] == s) & (t["budget"] == BUDGET)].iloc[0]
    rule, ai = get("rule4w"), get("ai")
    target = float(rule["served_rate"])
    out = {"source_file": src, "split": "test", "budget_highlight": BUDGET,
           "none": {"moves": 0.0, "served_rate": round(float(none["served_rate"]), 4)}, "at_budget": {}, "curves": {}}
    for s, *_ in LINES:
        r = get(s)
        out["at_budget"][s] = {"moves_per_night": round(float(r["moves_per_night"]), 1), "served_rate": round(float(r["served_rate"]), 4)}
        d = t[t["strategy"] == s].sort_values("budget")
        out["curves"][s] = [{"budget": int(b), "moves": round(float(m), 1), "served_rate": round(float(v), 4)}
                            for b, m, v in zip(d["budget"], d["moves_per_night"], d["served_rate"])]
    need = {s: interp_moves(t[t["strategy"] == s], target) for s in ("ai", "ai_weather", "oracle")}
    out["same_success"] = {"target_served_rate": round(target, 4), "rule_moves_at_1500": round(float(rule["moves_per_night"]), 1),
                           "method": "경험 규칙의 예산 1500 성공률을 각 곡선이 처음 넘는 두 측정점 사이 선형 보간"}
    for s, m in need.items():
        diff = float(rule["moves_per_night"]) - m
        out["same_success"][s] = {"moves_needed": round(m, 1), "saving_moves": round(diff, 1),
                                  "saving_pct": round(diff / float(rule["moves_per_night"]) * 100, 2)}
    out["gain_at_budget_1500_pp"] = {s: round((float(get(s)["served_rate"]) - target) * 100, 2) for s in ("ai", "ai_weather", "oracle")}

    fig, ax = plt.subplots(figsize=(100 * S.MM, 64 * S.MM))
    fig.subplots_adjust(left=0.075, right=0.775, top=0.935, bottom=0.145)
    ax.set_xlim(-45, 1700)
    ax.set_ylim(54, 100)
    draw(ax, t)
    ax.plot(0, none["served_rate"] * 100, "o", ms=4, mfc="white", mec=S.INK2, mew=1.0, zorder=5, clip_on=False)
    ax.text(40, none["served_rate"] * 100 - 0.3, f"재배치 없음 {none['served_rate']*100:.1f}%", fontsize=S.FS_SMALL, color=S.INK2,
            va="center", ha="left")
    # 오른쪽 끝 직접 라벨(겹치면 간격 조정 + 연결선)
    ends = [(s, t[t["strategy"] == s].sort_values("budget").iloc[-1]) for s, *_ in LINES]
    ly = spread([float(r["served_rate"]) * 100 for _, r in ends], 3.1)
    for (s, r), y, spec in zip(ends, ly, LINES):
        x0, y0 = float(r["moves_per_night"]), float(r["served_rate"]) * 100
        ax.plot([x0 + 12, 1722], [y0, y], color=spec[2], lw=0.6, zorder=2, clip_on=False)
        ax.text(1735, y, spec[1], fontsize=S.FS_SMALL, color=spec[5], fontweight="bold" if spec[6] else "normal",
                va="center", ha="left", clip_on=False)
    ax.set_xticks([0, 500, 1000, 1500])
    ax.set_xticklabels(["0", "500", "1,000", "1,500"], fontsize=S.FS_SMALL)
    ax.set_yticks([60, 70, 80, 90, 100])
    ax.set_yticklabels(["60", "70", "80", "90", "100"], fontsize=S.FS_SMALL)
    ax.grid(color=S.GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.spines[["left", "bottom"]].set_visible(False)
    ax.set_xlabel("밤당 실제 이동 대수(평균, 대)", fontsize=S.FS_SMALL, color=S.INK2, labelpad=3)
    ax.set_title("가상 운영 대여 성공률(%)", fontsize=S.FS_SMALL, loc="left", color=S.INK2, pad=4, x=-0.07)

    # 확대 창: 예산 1500 부근에서 곡선 간 차이가 보이도록
    X0, X1, Y0, Y1 = 1150, 1670, 94.0, 99.3
    ins = ax.inset_axes([0.47, 0.12, 0.51, 0.40])
    ins.set_xlim(X0, X1)
    ins.set_ylim(Y0, Y1)
    draw(ins, t, 0.9)
    ins.axhline(target * 100, color=S.ACCENT, lw=0.6, ls=(0, (2, 2)), zorder=2)
    m_ai = need["ai"]
    if m_ai == m_ai:  # NaN이 아니면
        ins.annotate("", xy=(m_ai, target * 100), xytext=(float(rule["moves_per_night"]), target * 100),
                     arrowprops=dict(arrowstyle="-|>", color=S.FOREST, lw=0.9, shrinkA=0, shrinkB=0, mutation_scale=6), zorder=6)
        sv = out["same_success"]["ai"]
        # 설명은 확대 창 밖 빈 영역(곡선 아래)에 두어 확대 창의 선과 겹치지 않게 한다
        ax.text(0.385, 0.25, f"같은 성공률({target*100:.1f}%)에서\nAI 예측은 밤당 이동\n{abs(sv['saving_moves']):.0f}대({abs(sv['saving_pct']):.1f}%) 절감",
                transform=ax.transAxes, fontsize=7.5, color=S.FOREST, va="center", ha="right", linespacing=1.2)
    ins.text(X1 - 10, Y0 + 0.2, "점: 예산 1,500", fontsize=7.5, color=S.INK2, va="bottom", ha="right")
    ins.set_xticks([1200, 1400, 1600])
    ins.set_xticklabels(["1,200", "1,400", "1,600"], fontsize=7.5)
    ins.set_yticks([95, 97, 99])
    ins.set_yticklabels(["95", "97", "99"], fontsize=7.5)
    ins.grid(color=S.GRID, linewidth=0.5)
    ins.set_axisbelow(True)
    ins.tick_params(length=0, pad=2)
    for sp in ins.spines.values():
        sp.set_visible(True)
        sp.set_color(S.CONTEXT)
        sp.set_linewidth(0.6)
    ins.set_title("확대", fontsize=7.5, loc="left", color=S.INK2, pad=2)

    (S.FIG_DIR / "policy_frontier.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("source_file", "none", "at_budget", "same_success", "gain_at_budget_1500_pp")}, ensure_ascii=False))
    print(S.save(fig, "policy_frontier"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
