"""창원시의회 누비자 발언(2020.4~2026.9) LLM 분류 결과: 쟁점별 비중 가로 막대.

입력: data/processed/civic_text/llm/summary.json (scripts/ai/classify_council_llm.py 출력)
재배치·형평·환경(이 연구가 다루는 쟁점)만 강조색, 나머지는 회색
"""
from __future__ import annotations

import json

import matplotlib.pyplot as plt

import style as S

FOCUS = {"재배치", "형평", "환경"}


def main() -> None:
    S.setup()
    d = json.loads((S.ROOT / "data/processed/civic_text/llm/summary.json").read_text(encoding="utf-8"))
    share = {k: v for k, v in d["code_share_of_relevant"].items() if k != "기타"}
    items = sorted(share.items(), key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(84 / 25.4, 52 / 25.4))
    y = range(len(items))
    colors = [S.ACCENT if k in FOCUS else S.CONTEXT for k, _ in items]
    ax.barh(list(y), [v * 100 for _, v in items], color=colors, height=0.62)
    for i, (k, v) in enumerate(items):
        ax.text(v * 100 + 0.6, i, f"{v * 100:.0f}%", va="center", fontsize=7.5,
                color=S.FOREST if k in FOCUS else S.INK2, fontweight="bold" if k in FOCUS else "normal")
    ax.set_yticks(list(y), [k for k, _ in items], fontsize=8)
    for t, (k, _) in zip(ax.get_yticklabels(), items):
        if k in FOCUS:
            t.set_color(S.FOREST)
            t.set_fontweight("bold")
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(share.values()) * 100 * 1.18)
    ax.set_xticks([])
    for sp in ("top", "right", "bottom"):
        ax.spines[sp].set_visible(False)
    S.save(fig, "council_issues")
    a = d["agreement"]
    out = {"utterances": d["utterances"], "relevant": d["relevant"], "share_of_relevant": share,
           "code_counts": d["code_counts"], "relevant_agreement": a["relevant_agreement"],
           "relevant_kappa": a["relevant_kappa"], "primary_code_agreement": a["primary_code_agreement"],
           "second_coder_n": a["n"], "per_code_kappa": {k: v["kappa"] for k, v in a["per_code"].items()},
           "by_year": d["by_year"], "note": "비중 = 쟁점 언급 발언 수 / 관련 발언 수(발언당 최대 2개 쟁점)"}
    (S.FIG_DIR / "council_issues.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
