"""AI 야간 배치 브리핑: 시뮬레이터의 하룻밤 배치안 → LLM 지시서 초안 → 숫자 자동 검증 → (재작성) → 사람 승인.

LangGraph 상태 그래프(체크포인터·thread_id·interrupt 사용)
  facts(결정론) → draft(LLM) → verify(결정론) ─실패·재시도<3→ revise(LLM) → verify
                                              └통과 또는 재시도 소진→ human_review(interrupt) → save
- 숫자는 코드가 만든 배치표(facts)에만 있고, LLM은 문장만 쓴다. 배치표에 없는 숫자·거점명이 나오면 검증 실패
- 실행: python scripts/ai/dispatch_brief.py --date 2025-04-15 [--auto-approve]
  --auto-approve 없이 실행하면 검토 단계에서 멈추고, 같은 thread로 승인/수정 입력을 받는다
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Literal, TypedDict

import duckdb
import numpy as np
import pandas as pd
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_rebalancing_experiments as R  # noqa: E402
from llm import call  # noqa: E402
from simulate_rebalancing import DAY, Trips, simulate  # noqa: E402

OUT = ROOT / "outputs" / "ai_brief"
CAPACITY = 20
MAX_REVISIONS = 2


# ---------------- 1) 배치안 재현(시험기간, 주 형평 정책) ----------------
def night_plan(date: str, strategy: str = "ai_fair", budget: int = 1500) -> dict:
    meta = json.loads((R.OUT / "meta_v2.json").read_text(encoding="utf-8"))
    alpha, beta = meta["tuned"][strategy]["alpha"], meta["tuned"][strategy]["beta"]
    source, ggroup, g, _, _ = R.STRATEGIES[strategy]
    con = duckdb.connect()
    stations = pd.read_csv(R.CHAINS / "stations.csv")
    sids = sorted(set(con.execute(f"select distinct o from '{(R.CHAINS / 'trips_valid.parquet').as_posix()}' union "
                                  f"select distinct d from '{(R.CHAINS / 'trips_valid.parquet').as_posix()}'").df().iloc[:, 0].astype(int)))
    idx = {s: i for i, s in enumerate(sids)}
    start, end = R.PERIODS["test"]
    trips, pos, t0 = R.load_inputs(start, end, con)
    tr = Trips(ts=R.epoch_s(trips["ts"]), o=trips["o"].map(idx).to_numpy(), te=R.epoch_s(trips["te"]),
               d=trips["d"].map(idx).to_numpy())
    pend = pos[pos["pending_te"].notna()]
    pending = [(float(np.datetime64(t, "s").astype("int64")), idx[int(dd)]) for t, dd in zip(pend["pending_te"], pend["pending_d"])]
    avail = pos[pos["pending_te"].isna() & pos["next_ts"].notna() & (pos["next_ts"] <= t0 + pd.Timedelta(days=7))]
    init = np.bincount(avail["next_o"].astype(int).map(idx), minlength=len(sids))
    days = list(pd.date_range(start, date, freq="D"))
    day_starts = [float(np.datetime64(d, "s").astype("int64")) for d in days]
    qp = pd.read_parquet(R.FORECAST / "q_pred_test.parquet")
    qp["day"] = pd.to_datetime(qp["day"])
    col = {"ai": "q_ai", "ai_weather": "q_ai_oracle_weather", "rule4w": "q_rule4w"}[source]
    grp = pd.read_csv(R.OUT / "station_groups.csv")
    vul = np.zeros(len(sids), bool)
    for s in grp.loc[grp["group"] == ggroup, "station_id"].astype(int):
        if s in idx:
            vul[idx[s]] = True
    lam, guar = {}, {}
    for d, ds in zip(days, day_starts):
        g_ = qp[qp["day"] == d]
        arr = np.zeros(len(sids))
        ii = g_["station_id"].astype(int).map(idx)
        arr[ii.to_numpy()] = alpha * g_[col].to_numpy(float) + beta   # 파일에 있는 거점 = 대상 거점
        lam[ds] = arr
        target = np.zeros(len(sids), bool)
        target[ii.to_numpy()] = True
        guar[ds] = np.where(vul & target, g, 0)                        # 보장도 대상 거점에만(실험 v2와 같은 규칙)
    res = simulate(tr, init, pending, day_starts, lam, budget, guarantee=guar,
                   period_end=day_starts[-1] + DAY + 2 * 3600)
    _, pickups, drops = res.moves_per_night[-1]
    st = stations.set_index("station_id")
    lam_d = lam[day_starts[-1]]

    lat0, lon0 = 35.22, 128.65
    known = st.index
    nm = lambda s: st.loc[s, "name"] if s in known else f"미등록 거점 {s}"   # 터미널 대장에 없는 반납 전용 번호(예: 7)

    def info(i, n):
        s = sids[i]
        return {"station": nm(s), "district": st.loc[s, "district"] if s in known else "미상", "bikes": int(n),
                "elev_m": int(round(float(st.loc[s, "elev_m"]))) if s in known and pd.notna(st.loc[s, "elev_m"]) else None,
                "vulnerable": bool(vul[i]), "expected_need": int(math.ceil(lam_d[i]))}
    drop_list = sorted([info(i, n) for i, n in drops.items()], key=lambda x: -x["bikes"])
    pick_list = sorted([info(i, n) for i, n in pickups.items()], key=lambda x: -x["bikes"])
    # 좌표 없는 거점은 실험 코드와 같이 기준점(35.22, 128.65)으로 둔다
    coord = lambda s, c, d0: st.loc[s, c] if s in known and pd.notna(st.loc[s, c]) else d0
    xy = {sids[i]: np.array([(coord(sids[i], "lon", lon0) - lon0) * 111.32 * np.cos(np.radians(lat0)),
                             (coord(sids[i], "lat", lat0) - lat0) * 110.57]) for i in set(pickups) | set(drops)}
    depot = 243
    xy[depot] = np.array([(st.loc[depot, "lon"] - lon0) * 111.32 * np.cos(np.radians(lat0)), (st.loc[depot, "lat"] - lat0) * 110.57])
    runs = truck_runs({sids[i]: n for i, n in pickups.items()}, {sids[i]: n for i, n in drops.items()}, xy, depot)
    for r in runs:
        r["stops"] = [{"station": nm(s), "action": a, "bikes": k} for s, a, k in r["stops"]]
    return {"date": date, "strategy": strategy, "budget_per_night": budget, "moved_bikes": int(sum(drops.values())),
            "pickup_stations": len(pickups), "drop_stations": len(drops),
            "vulnerable_drop_stations": sum(1 for d in drop_list if d["vulnerable"]),
            "vulnerable_bikes": sum(d["bikes"] for d in drop_list if d["vulnerable"]),
            "truck_runs": len(runs), "route_km": round(sum(r["km"] for r in runs), 1),
            "top_drops": drop_list[:8], "top_pickups": pick_list[:6],
            "first_runs": runs[:3], "alpha": alpha, "beta": beta}


def truck_runs(pick: dict, drop: dict, xy: dict, depot: int) -> list[dict]:
    """시뮬레이터 route_km과 같은 탐욕 규칙으로 회차(적재 0으로 돌아오는 단위)별 정차 순서를 만든다."""
    pick, drop = dict(pick), dict(drop)
    pos, load, runs, cur = xy[depot], 0, [], {"stops": [], "km": 0.0}
    while pick or drop:
        cands = ([(s, "수거") for s in pick] if load < CAPACITY else []) + ([(s, "배치") for s in drop] if load > 0 else [])
        if not cands:
            break
        dists = [float(np.hypot(*(xy[s] - pos))) for s, _ in cands]
        j = int(np.argmin(dists))
        s, a = cands[j]
        cur["km"] += dists[j]
        pos = xy[s]
        if a == "수거":
            k = min(CAPACITY - load, pick[s]); load += k; pick[s] -= k
            if pick[s] == 0:
                del pick[s]
        else:
            k = min(load, drop[s]); load -= k; drop[s] -= k
            if drop[s] == 0:
                del drop[s]
        cur["stops"].append((s, a, k))
        if load == 0 and a == "배치":
            cur["km"] = round(cur["km"], 1)
            runs.append(cur)
            cur = {"stops": [], "km": 0.0}
    if cur["stops"]:
        cur["km"] = round(cur["km"], 1)
        runs.append(cur)
    return runs


# ---------------- 2) LangGraph ----------------
class BriefState(TypedDict, total=False):
    facts: dict
    draft: str
    errors: list
    revisions: int
    approved: bool
    reviewer_note: str
    log: list


SYSTEM = ("너는 창원 공영자전거 누비자 재배치 운영팀의 야간 배치 브리핑 작성 보조다. "
          "주어진 배치표(JSON)의 숫자와 거점 이름만 사용한다. 계산하거나 새로운 숫자를 만들지 않는다. 한국어 개조식으로 쓴다.")
TEMPLATE = """아래 배치표로 오늘 밤 재배치 차량 운전원과 관리자에게 보낼 브리핑을 작성하라.
형식(마크다운, 700자 이내):
1) 오늘 밤 요약 3줄: 옮길 자전거 대수, 수거·배치 거점 수, 차량 회차 수와 경로 거리
2) 우선 배치 거점: 배치 대수가 많은 순으로 최대 5곳(거점명·대수, 취약 거점이면 '최소 보장' 표시)
3) 1회차 경로: 정차 순서대로(거점명·수거/배치·대수)
4) 확인 요청 1줄: 현장 재고가 배치표와 다르면 보고
규칙: 배치표에 없는 숫자 금지(날짜와 목록 번호 제외), 배치표에 없는 거점명 금지, 추측·홍보 문구 금지.

배치표:
{facts}"""


def _numbers(text: str) -> list[str]:
    return [m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def allowed_numbers(facts: dict) -> set[str]:
    nums = set(_numbers(json.dumps(facts, ensure_ascii=False)))
    y, m, d = facts["date"].split("-")
    nums |= {y, str(int(m)), str(int(d)), m, d} | {str(i) for i in range(1, 11)}
    out = set()
    for n in nums:
        out.add(n)
        try:
            f = float(n)
            out |= {str(int(f)) if f == int(f) else n, f"{f:.1f}", f"{f:.0f}"}
        except ValueError:
            pass
    return out


def node_draft(state: BriefState) -> BriefState:
    r = call(TEMPLATE.format(facts=json.dumps(state["facts"], ensure_ascii=False, indent=1)), SYSTEM, model="sonnet")
    return {"draft": r["text"], "revisions": 0, "log": state.get("log", []) + [{"step": "draft", "model": r["model"], "cost_usd": r["cost_usd"]}]}


def node_verify(state: BriefState) -> BriefState:
    facts, text = state["facts"], state["draft"]
    ok = allowed_numbers(facts)
    bad_nums = sorted({n for n in _numbers(text) if n not in ok})
    names = set(pd.read_csv(R.CHAINS / "stations.csv")["name"].astype(str))
    in_plan = {d["station"] for d in facts["top_drops"] + facts["top_pickups"]} | \
        {s["station"] for r in facts["first_runs"] for s in r["stops"]}
    bad_names = sorted({nm for nm in names if len(nm) >= 3 and nm in text and nm not in in_plan})
    errors = [f"배치표에 없는 숫자: {n}" for n in bad_nums] + [f"배치표에 없는 거점: {n}" for n in bad_names]
    return {"errors": errors, "log": state["log"] + [{"step": "verify", "errors": errors}]}


def route_after_verify(state: BriefState) -> Literal["revise", "human_review"]:
    return "revise" if state["errors"] and state.get("revisions", 0) < MAX_REVISIONS else "human_review"


def node_revise(state: BriefState) -> BriefState:
    prompt = (TEMPLATE.format(facts=json.dumps(state["facts"], ensure_ascii=False, indent=1))
              + "\n\n이전 초안:\n" + state["draft"] + "\n\n검증 오류(반드시 고칠 것):\n- " + "\n- ".join(state["errors"]))
    r = call(prompt, SYSTEM, model="sonnet")
    return {"draft": r["text"], "revisions": state.get("revisions", 0) + 1,
            "log": state["log"] + [{"step": "revise", "model": r["model"], "cost_usd": r["cost_usd"]}]}


def node_human_review(state: BriefState) -> Command[Literal["save", "__end__"]]:
    decision = interrupt({"draft": state["draft"], "errors": state["errors"],
                          "action": "승인(approved=true) 또는 반려. 수정 시 edited에 최종 문안"})
    if decision.get("approved"):
        return Command(update={"approved": True, "draft": decision.get("edited") or state["draft"],
                               "reviewer_note": decision.get("note", "")}, goto="save")
    return Command(update={"approved": False, "reviewer_note": decision.get("note", "")}, goto=END)


def node_save(state: BriefState) -> BriefState:
    OUT.mkdir(parents=True, exist_ok=True)
    d = state["facts"]["date"].replace("-", "")
    (OUT / f"brief_{d}.md").write_text(state["draft"], encoding="utf-8")
    (OUT / f"brief_{d}_record.json").write_text(json.dumps(
        {"facts": state["facts"], "draft": state["draft"], "final_errors": state["errors"], "revisions": state.get("revisions", 0),
         "approved": state["approved"], "reviewer_note": state.get("reviewer_note", ""), "log": state["log"]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {}


def build_graph():
    g = StateGraph(BriefState)
    g.add_node("draft", node_draft)
    g.add_node("verify", node_verify)
    g.add_node("revise", node_revise)
    g.add_node("human_review", node_human_review)
    g.add_node("save", node_save)
    g.add_edge(START, "draft")
    g.add_edge("draft", "verify")
    g.add_conditional_edges("verify", route_after_verify)
    g.add_edge("revise", "verify")
    g.add_edge("save", END)
    return g.compile(checkpointer=InMemorySaver())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2025-04-15")
    ap.add_argument("--auto-approve", action="store_true", help="시연용: 검토자가 오류 없는 초안을 승인한 것으로 처리")
    args = ap.parse_args()
    facts = night_plan(args.date)
    graph = build_graph()
    cfg = {"configurable": {"thread_id": f"brief-{args.date}"}}
    out = graph.invoke({"facts": facts, "log": []}, cfg)
    pending = out.get("__interrupt__")
    if pending:
        payload = pending[0].value
        print("=== 검토 대기 초안 ===\n" + payload["draft"] + "\n=== 남은 검증 오류 ===\n" + json.dumps(payload["errors"], ensure_ascii=False))
        if args.auto_approve and not payload["errors"]:
            out = graph.invoke(Command(resume={"approved": True, "note": "시연: 분석자가 배치표와 대조 후 승인"}), cfg)
        else:
            ans = input("승인하시겠습니까? (y/n): ").strip().lower()
            out = graph.invoke(Command(resume={"approved": ans == "y", "note": "콘솔 검토"}), cfg)
    print(json.dumps({"approved": out.get("approved"), "revisions": out.get("revisions"), "errors": out.get("errors")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
