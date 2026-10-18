import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "ai"))
from dispatch_brief import verify_draft  # noqa: E402

FACTS = {"date": "2025-04-15", "budget_per_night": 1500, "moved_bikes": 1500,
         "top_drops": [{"station": "창원중앙도서관", "bikes": 46}, {"station": "진해고등학교", "bikes": 38}],
         "top_pickups": [{"station": "상남오거리", "bikes": 59}],
         "first_runs": [{"km": 3.6, "stops": [{"station": "창원시청 후문 버스정류소", "action": "수거", "bikes": 2},
                                               {"station": "창원시청", "action": "배치", "bikes": 2},
                                               {"station": "창원중앙도서관", "action": "배치", "bikes": 4}]}]}
KNOWN = {"창원중앙도서관", "진해고등학교", "상남오거리", "창원시청", "창원시청 후문 버스정류소", "용호동주민센터"}


class TestVerifyDraft(unittest.TestCase):
    def test_correct_draft_passes(self):
        text = "옮길 자전거 1500대\n1. 창원중앙도서관 46대 (최소 보장)\n2. 진해고등학교 38대\n창원시청 후문 버스정류소 수거 2 → 창원시청 배치 2"
        self.assertEqual(verify_draft(FACTS, text, KNOWN), [])

    def test_wrong_count_for_planned_station(self):        # Codex 반례 ①: 38은 다른 거점 값이라 숫자 검사는 통과
        errs = verify_draft(FACTS, "창원중앙도서관 38대 배치", KNOWN)
        self.assertTrue(any(e.startswith("거점-대수 불일치: 창원중앙도서관 38대") for e in errs), errs)

    def test_fake_station(self):                           # Codex 반례 ②: 대장에 없는 이름
        errs = verify_draft(FACTS, "검토용가상거점 38대 배치", KNOWN)
        self.assertIn("계획에 없는 거점 의심: 검토용가상거점 38대", errs)

    def test_known_station_outside_plan(self):
        self.assertIn("배치표에 없는 거점: 용호동주민센터", verify_draft(FACTS, "용호동주민센터 2대", KNOWN))

    def test_saved_record_passes(self):                    # 저장된 실제 초안(로컬에만 있음)
        rec = ROOT / "outputs" / "ai_brief" / "brief_20250415_record.json"
        if not rec.exists():
            self.skipTest("저장 초안 없음")
        r = json.loads(rec.read_text(encoding="utf-8"))
        import pandas as pd
        names = set(pd.read_csv(ROOT / "data" / "processed" / "bike_chains" / "stations.csv")["name"].astype(str))
        self.assertEqual(verify_draft(r["facts"], r["draft"], names), [])


if __name__ == "__main__":
    unittest.main()
