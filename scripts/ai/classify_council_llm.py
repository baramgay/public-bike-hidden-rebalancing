"""창원시의회 회의록 '누비자' 발언을 LLM으로 코드북 분류하고, 다른 모델의 독립 재분류로 일치도를 검증한다.

입력: data/processed/civic_text/nubija_utterances.csv (671행, 수집: scripts/collection/civic_text_collect.py)
출력: data/processed/civic_text/llm/ (원응답 JSONL, 분류표, 일치도, 요약)
- 1차 코더: Claude Haiku(전수), 2차 코더: Claude Sonnet(무작위 표본, seed 42)
- 발언자 이름은 프롬프트에 넣지 않고 직위만 넣는다
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import call, parse_json_block  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "processed" / "civic_text" / "nubija_utterances.csv"
OUT = ROOT / "data" / "processed" / "civic_text" / "llm"
CODES = ["재배치", "정비", "확충", "이용", "재정", "안전", "연계", "형평", "환경", "관광", "기타"]
STANCES = ["문제제기", "개선요구", "현황설명", "기타"]
SYSTEM = "너는 지방의회 회의록 발언을 정해진 코드북으로 분류하는 연구 보조자다. 설명 없이 JSON 배열만 출력한다."
CODEBOOK = """다음은 창원시의회 회의록에서 공영자전거 '누비자'가 언급된 발언이다. 각 발언을 아래 코드북으로 분류하라.

[relevant] 누비자(공영자전거) 정책·운영에 대한 실질적 내용이 있으면 true. 인사·호명·"답변드리겠습니다" 같은 형식적 발언, 누비자가 다른 주제 속 지나가는 예시로만 나오면 false.
[codes] relevant가 true일 때만, 해당하는 쟁점을 최대 2개(중심 쟁점 먼저). false면 빈 배열.
- 재배치: 자전거 쏠림·부족, 재배치·배송 차량·인력, 거치대가 비거나 가득 참
- 정비: 고장·정비·노후·자전거 교체·관리 품질
- 확충: 터미널·거치대 신설·이전·위치, 서비스 지역 확대
- 이용: 이용 실적·수요·이용률 증감·회원
- 재정: 예산·적자·운영비·요금·수익
- 안전: 사고·안전·보험·자전거도로 안전
- 연계: 버스·철도 등 대중교통 연계, 자전거도로망, 교통정책 전반
- 형평: 외곽·소외지역·교통약자·고령자의 접근
- 환경: 탄소·기후·친환경 효과
- 관광: 관광·여가·홍보·행사
- 기타: 위에 없는 내용
[stance] 문제제기 / 개선요구 / 현황설명 / 기타 중 하나
출력 형식: [{"id": 번호, "relevant": true 또는 false, "codes": [...], "stance": "..."}] — 입력의 모든 번호를 순서대로 포함, JSON 배열만.

발언 목록:
"""
BATCH = 25
SECOND_SAMPLE = 100


def classify(df: pd.DataFrame, model: str, tag: str) -> pd.DataFrame:
    raw_path = OUT / f"raw_{tag}.jsonl"
    done = {}
    if raw_path.exists():                      # 중단 후 재실행 시 이어서
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            for item in rec["parsed"]:
                done[int(item["id"])] = item
    todo = df[~df["id"].isin(done)]
    with raw_path.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), BATCH):
            chunk = todo.iloc[i:i + BATCH]
            lines = [f"[{r.id}] ({r.speaker}) {str(r.text).strip()[:1200]}" for r in chunk.itertuples()]
            prompt = CODEBOOK + "\n".join(lines)
            for attempt in range(3):
                try:
                    res = call(prompt, SYSTEM, model=model)
                    parsed = parse_json_block(res["text"])
                    ids = {int(x["id"]) for x in parsed}
                    if not set(chunk["id"]) <= ids:
                        raise ValueError(f"누락 id {sorted(set(chunk['id']) - ids)[:5]}")
                    break
                except Exception as e:          # noqa: BLE001 — 응답 형식 오류는 재시도
                    print(f"  재시도 {attempt + 1}: {e}", flush=True)
                    time.sleep(2)
            else:
                raise SystemExit(f"{tag} 배치 {i} 실패")
            fh.write(json.dumps({"batch_start": i, "model": res["model"], "cost_usd": res["cost_usd"],
                                 "prompt_ids": chunk["id"].tolist(), "response": res["text"], "parsed": parsed},
                                ensure_ascii=False) + "\n")
            fh.flush()
            for item in parsed:
                done[int(item["id"])] = item
            print(f"{tag}: {min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
    rows = []
    for rid in df["id"]:
        it = done[int(rid)]
        codes = [c for c in it.get("codes", []) if c in CODES][:2]
        rows.append({"id": int(rid), "relevant": bool(it.get("relevant")), "codes": "|".join(codes),
                     "stance": it.get("stance") if it.get("stance") in STANCES else "기타"})
    return pd.DataFrame(rows)


def kappa(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(int), b.astype(int)
    po = float((a == b).mean())
    pe = float(a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean()))
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SRC)
    df = df.reset_index().rename(columns={"index": "id", "발언자 직위": "speaker", "발언 원문": "text"})
    first = classify(df, "haiku", "haiku")
    first.to_csv(OUT / "codes_haiku.csv", index=False, encoding="utf-8-sig")
    sample = df.sample(SECOND_SAMPLE, random_state=42).sort_values("id")
    second = classify(sample, "sonnet", "sonnet_sample")
    second.to_csv(OUT / "codes_sonnet_sample.csv", index=False, encoding="utf-8-sig")

    m = first.merge(second, on="id", suffixes=("_h", "_s"))
    agree = {"n": int(len(m)), "relevant_agreement": float((m["relevant_h"] == m["relevant_s"]).mean()),
             "relevant_kappa": kappa(m["relevant_h"].to_numpy(), m["relevant_s"].to_numpy())}
    both = m[m["relevant_h"] & m["relevant_s"]]
    agree["both_relevant_n"] = int(len(both))
    agree["primary_code_agreement"] = float((both["codes_h"].str.split("|").str[0] ==
                                             both["codes_s"].str.split("|").str[0]).mean()) if len(both) else float("nan")
    per_code = {}
    for c in CODES:
        ha = both["codes_h"].str.split("|").apply(lambda x: c in x).to_numpy()
        so = both["codes_s"].str.split("|").apply(lambda x: c in x).to_numpy()
        if ha.sum() + so.sum() >= 3:
            per_code[c] = {"haiku": int(ha.sum()), "sonnet": int(so.sum()), "kappa": round(kappa(ha, so), 3)}
    agree["per_code"] = per_code

    full = df.merge(first, on="id")
    full["year"] = full["회의일"].astype(str).str[:4]
    rel = full[full["relevant"]]
    exploded = rel.assign(code=rel["codes"].str.split("|")).explode("code")
    exploded = exploded[exploded["code"].fillna("") != ""]
    summary = {"utterances": int(len(full)), "relevant": int(len(rel)),
               "code_counts": exploded["code"].value_counts().to_dict(),
               "code_share_of_relevant": (exploded["code"].value_counts() / len(rel)).round(4).to_dict(),
               "by_year": exploded.groupby(["year", "code"]).size().unstack(fill_value=0).to_dict(orient="index"),
               "stance_counts": rel["stance"].value_counts().to_dict(),
               "agreement": agree}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    full[["id", "회의일", "회의명", "speaker", "relevant", "codes", "stance", "출처 URL"]].to_csv(
        OUT / "utterances_coded.csv", index=False, encoding="utf-8-sig")
    print(json.dumps({k: summary[k] for k in ("utterances", "relevant", "code_counts", "stance_counts", "agreement")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
