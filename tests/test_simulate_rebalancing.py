import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "analysis"))
from simulate_rebalancing import (DAY, Trips, plan_moves, q_from_hourly, route_km,  # noqa: E402
                                  service_overlap, simulate)

H = 3600


class TestRebalancing(unittest.TestCase):
    def test_service_overlap(self):
        self.assertEqual(service_overlap(4 * H, 6 * H), H)                 # 05~06시만
        self.assertEqual(service_overlap(23 * H, DAY + 6 * H), 2 * H)      # 23~24시 + 다음날 05~06시
        self.assertEqual(service_overlap(1 * H, 4 * H), 0)

    def test_q_from_hourly_rentals_first(self):
        self.assertEqual(q_from_hourly(np.array([[3, 0, 1]]), np.array([[0, 2, 0]]))[0], 3)
        self.assertEqual(q_from_hourly(np.array([[1, 1]]), np.array([[1, 0]]))[0], 1)
        self.assertEqual(q_from_hourly(np.array([[0, 0]]), np.array([[2, 0]]))[0], 0)

    def test_plan_guarantee_then_value(self):
        p, d = plan_moves(np.array([5, 0, 0]), np.zeros(3), budget=5, guarantee=np.array([0, 1, 1]))
        self.assertEqual(p, {0: 2})
        self.assertEqual(d, {1: 1, 2: 1})

    def test_plan_respects_budget_and_value(self):
        p, d = plan_moves(np.array([4, 0]), np.array([0.0, 3.0]), budget=2)
        self.assertEqual((p, d), ({0: 2}, {1: 2}))
        p, d = plan_moves(np.array([4, 0]), np.array([0.0, 3.0]), budget=10)
        self.assertEqual(sum(p.values()), sum(d.values()))
        self.assertLessEqual(sum(d.values()), 4)

    def test_simulate_rebalancing_enables_rentals(self):
        trips = Trips(ts=np.array([8 * H, 9 * H], dtype=float), o=np.array([0, 0]),
                      te=np.array([8 * H + 600, 9 * H + 600], dtype=float), d=np.array([1, 1]))
        lam = {0.0: np.array([2.0, 0.0])}
        no = simulate(trips, np.array([0, 2]), [], [0.0], lam, budget=0)
        yes = simulate(trips, np.array([0, 2]), [], [0.0], lam, budget=2)
        self.assertEqual((no.total_served, no.total_demand), (0, 2))
        self.assertEqual((yes.total_served, yes.total_demand), (2, 2))
        # 무재배치: 거점0은 05시부터 하루 종일 빈 상태
        self.assertEqual(no.zero_service_s[0], 19 * H)
        # 재배치: 08:00·09:00 두 대가 나가 09:00부터 빈 상태(19시간 중 15시간)
        self.assertEqual(yes.zero_service_s[0], 15 * H)

    def test_lost_rental_has_no_return(self):
        trips = Trips(ts=np.array([8 * H], dtype=float), o=np.array([0]), te=np.array([8 * H + 60], dtype=float),
                      d=np.array([1]))
        r = simulate(trips, np.array([0, 0]), [], [0.0], {}, budget=0)
        self.assertEqual(r.total_served, 0)
        self.assertEqual(r.lost[0], 1)
        self.assertEqual(r.zero_service_s[1], 19 * H)   # 실패한 대여의 반납은 생기지 않음

    def test_route_km(self):
        xy = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
        self.assertAlmostEqual(route_km({1: 1}, {2: 1}, xy, depot=0), 4.0)
        # 용량 1이면 두 번 왕복
        self.assertAlmostEqual(route_km({1: 2}, {2: 2}, xy, depot=0, capacity=1), 1 + 1 + 1 + 1 + 2)


    def test_guarantee_per_day(self):
        # 날짜별 보장: 첫날만 거점1에 2대 보장, 둘째 날 보장 없음(λ=0이라 가치 이동도 없음)
        empty = Trips(ts=np.array([]), o=np.array([], int), te=np.array([]), d=np.array([], int))
        days = [0.0, float(DAY)]
        lam = {d: np.zeros(2) for d in days}
        guar = {days[0]: np.array([0, 2]), days[1]: np.array([0, 0])}
        res = simulate(empty, np.array([4, 0]), [], days, lam, 10, guarantee=guar)
        self.assertEqual(res.moves_per_night[0][2], {1: 2})
        self.assertEqual(res.moves_per_night[1][2], {})


if __name__ == "__main__":
    unittest.main()
