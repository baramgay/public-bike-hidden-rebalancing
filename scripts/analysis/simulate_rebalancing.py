"""관측 대여를 시간순으로 재생하며 야간 재배치 전략을 비교하는 시뮬레이터.

- 수요: 실제 관측된 대여(출발 거점·시각)와 그 반납(도착 거점·시각). 재고가 0이면 그 대여는 실패하고 반납도 사라진다.
- 재배치: 매일 02:00(01~04시는 대여가 거의 없음) 예산 M대 이내로 자전거를 옮긴다.
- 목표: 거점별 그날 필요 대수 q의 예측값 λ로 'k번째 자전거가 필요할 확률' P(Q>=k)를 포아송 꼬리로 근사해
  가장 가치가 큰 곳에 놓고 가장 덜 아까운 곳에서 가져오는 탐욕 배치. 전략 간 차이는 λ의 출처(예측 방법)와
  취약 거점 최소 보장뿐이다.
- 한계: 관측 대여만 재생하므로 빈 거점에서 포기된 수요는 없다(검열). 거치대 용량·주간 재배치는 모형에 없다.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import poisson

DAY = 86_400
SERVICE_START_S, SERVICE_END_S = 5 * 3600, 24 * 3600
REBALANCE_OFFSET_S = 2 * 3600


def service_overlap(a: float, b: float) -> float:
    """[a, b) 중 매일 05:00~24:00에 해당하는 초."""
    if b <= a:
        return 0.0
    total = 0.0
    day0 = math.floor(a / DAY) * DAY
    d = day0
    while d < b:
        lo, hi = max(a, d + SERVICE_START_S), min(b, d + SERVICE_END_S)
        if hi > lo:
            total += hi - lo
        d += DAY
    return total


@dataclass
class Trips:
    """시간순(출발) 정렬된 관측 이용. 시각은 초(naive KST epoch)."""
    ts: np.ndarray
    o: np.ndarray
    te: np.ndarray
    d: np.ndarray


@dataclass
class Result:
    served: np.ndarray
    lost: np.ndarray
    zero_service_s: np.ndarray
    moves_per_night: list = field(default_factory=list)  # [(day_start_s, pickups{idx:n}, drops{idx:n})]

    @property
    def total_served(self) -> int:
        return int(self.served.sum())

    @property
    def total_demand(self) -> int:
        return int(self.served.sum() + self.lost.sum())


def plan_moves(inv: np.ndarray, lam: np.ndarray, budget: int, guarantee: np.ndarray | None = None,
               weight: np.ndarray | None = None, min_gain: float = 0.0) -> tuple[dict, dict]:
    """한 번의 야간 재배치 계획. 반환: (pickups{idx:n}, drops{idx:n}).

    1) 보장 대수: guarantee[s]까지 부족한 거점에 먼저 채운다(가장 덜 아까운 거점에서 가져옴).
    2) 나머지 예산: 놓을 가치 P(Q_s >= I_s+1)*w_s 최대 거점 ← 뺄 손실 P(Q_s >= I_s)*w_s 최소 거점, 이득>min_gain일 때만.
    """
    inv = inv.astype(np.int64).copy()
    n = len(inv)
    w = np.ones(n) if weight is None else weight
    guar = np.zeros(n, dtype=np.int64) if guarantee is None else guarantee.astype(np.int64)
    pickups: dict[int, int] = {}
    drops: dict[int, int] = {}
    moved = 0
    # tail[s, k] = P(Q_s >= k). 큰 k는 0으로 둔다.
    lam = np.maximum(np.asarray(lam, dtype=float), 0.0)
    kmax = int(max(lam.max() + 10 * math.sqrt(lam.max()) + 25, 2))
    ks = np.arange(kmax)
    tail = poisson.sf(ks[None, :] - 1, lam[:, None])
    tail[:, 0] = 1.0

    def p_ge(s: int, k: int) -> float:
        return float(tail[s, k]) if k < kmax else 0.0

    def drop_value(s: int) -> float:
        return p_ge(s, int(inv[s]) + 1) * w[s]

    def pick_cost(s: int) -> float:
        if inv[s] <= 0 or inv[s] <= guar[s]:
            return math.inf
        return p_ge(s, int(inv[s])) * w[s]

    pick_heap = [(pick_cost(s), s) for s in range(n) if inv[s] > 0]
    heapq.heapify(pick_heap)

    def pop_pick(exclude: int) -> int | None:
        stash = []
        found = None
        while pick_heap:
            c, s = heapq.heappop(pick_heap)
            if c != pick_cost(s):          # 낡은 항목
                if inv[s] > 0:
                    heapq.heappush(pick_heap, (pick_cost(s), s))
                continue
            if math.isinf(c):
                stash.append((c, s))
                break
            if s == exclude:
                stash.append((c, s))
                continue
            found = s
            break
        for item in stash:
            heapq.heappush(pick_heap, item)
        return found

    def move(src: int, dst: int) -> None:
        nonlocal moved
        inv[src] -= 1
        inv[dst] += 1
        pickups[src] = pickups.get(src, 0) + 1
        drops[dst] = drops.get(dst, 0) + 1
        moved += 1
        if inv[src] > 0:
            heapq.heappush(pick_heap, (pick_cost(src), src))

    # 1) 최소 보장
    need = [(s, int(guar[s] - inv[s])) for s in range(n) if guar[s] > inv[s]]
    need.sort(key=lambda x: (-x[1], x[0]))
    for s, k in need:
        for _ in range(k):
            if moved >= budget:
                break
            src = pop_pick(exclude=s)
            if src is None:
                break
            move(src, s)

    # 2) 가치 기반 탐욕
    drop_heap = [(-drop_value(s), s) for s in range(n)]
    heapq.heapify(drop_heap)
    while moved < budget and drop_heap:
        neg_v, dst = heapq.heappop(drop_heap)
        v = -neg_v
        if v != drop_value(dst):
            heapq.heappush(drop_heap, (-drop_value(dst), dst))
            continue
        src = pop_pick(exclude=dst)
        if src is None:
            break
        c = pick_cost(src)
        if v - c <= min_gain:
            heapq.heappush(pick_heap, (c, src))
            break
        move(src, dst)
        heapq.heappush(drop_heap, (-drop_value(dst), dst))
    return pickups, drops


def simulate(trips: Trips, init_inv: np.ndarray, pending_returns: list[tuple[float, int]],
             day_starts: list[float], lam_by_day: dict[float, np.ndarray], budget: int,
             guarantee: np.ndarray | dict | None = None, weight: np.ndarray | None = None,
             min_gain: float = 0.0, period_end: float | None = None) -> Result:
    """day_starts: 각 날짜 00:00(초). 재배치는 각 날짜 02:00에 lam_by_day[day_start]로 수행."""
    n = len(init_inv)
    inv = init_inv.astype(np.int64).copy()
    served = np.zeros(n, dtype=np.int64)
    lost = np.zeros(n, dtype=np.int64)
    zero_s = np.zeros(n)
    t0 = day_starts[0] + REBALANCE_OFFSET_S
    zero_since = np.where(inv == 0, t0, -1.0)
    returns = list(pending_returns)
    heapq.heapify(returns)
    moves_log = []

    def add(s: int, k: int, t: float) -> None:
        if inv[s] == 0 and k > 0 and zero_since[s] >= 0:
            zero_s[s] += service_overlap(zero_since[s], t)
            zero_since[s] = -1.0
        inv[s] += k

    def remove(s: int, k: int, t: float) -> None:
        inv[s] -= k
        if inv[s] == 0:
            zero_since[s] = t

    i = 0
    m = len(trips.ts)
    ts, o, te, d = trips.ts, trips.o, trips.te, trips.d
    for day_start in day_starts:
        t_reb = day_start + REBALANCE_OFFSET_S
        t_next = day_start + DAY + REBALANCE_OFFSET_S
        # 재배치 직전까지의 반납
        while returns and returns[0][0] <= t_reb:
            tr, s = heapq.heappop(returns)
            add(s, 1, tr)
        if budget > 0 and day_start in lam_by_day:
            guar = guarantee.get(day_start) if isinstance(guarantee, dict) else guarantee   # 날짜별 보장 허용
            pickups, drops = plan_moves(inv, lam_by_day[day_start], budget, guar, weight, min_gain)
            for s, k in pickups.items():
                remove(s, k, t_reb)
            for s, k in drops.items():
                add(s, k, t_reb)
            moves_log.append((day_start, pickups, drops))
        # 다음 재배치 전까지 사건 재생 (같은 시각이면 대여 먼저)
        while i < m and ts[i] < t_next:
            t = ts[i]
            while returns and returns[0][0] < t:
                tr, s = heapq.heappop(returns)
                add(s, 1, tr)
            s = o[i]
            if inv[s] > 0:
                remove(s, 1, t)
                served[s] += 1
                heapq.heappush(returns, (float(te[i]), int(d[i])))
            else:
                lost[s] += 1
            i += 1
    end = period_end if period_end is not None else day_starts[-1] + DAY + REBALANCE_OFFSET_S
    while returns and returns[0][0] <= end:
        tr, s = heapq.heappop(returns)
        add(s, 1, tr)
    for s in range(n):
        if zero_since[s] >= 0:
            zero_s[s] += service_overlap(zero_since[s], end)
    return Result(served=served, lost=lost, zero_service_s=zero_s, moves_per_night=moves_log)


def q_from_hourly(dep: np.ndarray, ret: np.ndarray) -> np.ndarray:
    """시간대별 대여·반납(거점×시간)에서 '아침에 있어야 할 최소 대수' q. 같은 시간 안에서는 대여 먼저.

    q = max_k ( sum_{h<=k} dep_h - sum_{h<k} ret_h ), 0 이상.
    """
    cum_dep = np.cumsum(dep, axis=1)
    cum_ret_prev = np.concatenate([np.zeros((dep.shape[0], 1)), np.cumsum(ret, axis=1)[:, :-1]], axis=1)
    return np.maximum((cum_dep - cum_ret_prev).max(axis=1), 0.0)


def route_km(pickups: dict[int, int], drops: dict[int, int], xy_km: np.ndarray, depot: int,
             capacity: int = 20) -> float:
    """가장 가까운 가능 지점으로 가는 탐욕 경로(적재 용량 capacity). 직선거리 km 합(차고지 왕복 포함)."""
    pick = dict(pickups)
    drop = dict(drops)
    pos = xy_km[depot]
    load = 0
    dist = 0.0
    while pick or drop:
        cands = []
        if load < capacity:
            cands += [(s, "p") for s in pick]
        if load > 0:
            cands += [(s, "d") for s in drop]
        if not cands:
            break
        idx = np.array([s for s, _ in cands])
        dd = np.hypot(*(xy_km[idx] - pos).T)
        j = int(np.argmin(dd))
        s, kind = cands[j]
        dist += float(dd[j])
        pos = xy_km[s]
        if kind == "p":
            k = min(capacity - load, pick[s])
            load += k
            pick[s] -= k
            if pick[s] == 0:
                del pick[s]
        else:
            k = min(load, drop[s])
            load -= k
            drop[s] -= k
            if drop[s] == 0:
                del drop[s]
    dist += float(np.hypot(*(xy_km[depot] - pos)))
    return dist
