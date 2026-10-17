import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/analysis/build_monthly_quality_audit.py'


class MonthlyAuditOutputSafety(unittest.TestCase):
    def test_invalid_totals_leave_prior_outputs_untouched(self):
        spec = importlib.util.spec_from_file_location('monthly_audit_under_test', SCRIPT)
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / 'data/raw/nubija_trips'
            processed = root / 'data/processed/quality_audit'
            output = root / 'outputs/quality_audit'
            for folder in (raw, processed, output):
                folder.mkdir(parents=True)
            for year in (2023, 2024, 2025):
                (raw / f'nubija_trips_{year}.csv').write_text(f'출발일\n{year}-01-01\n', encoding='cp949')
            prior_csv = processed / 'monthly_departure_coverage.csv'
            prior_png = output / 'monthly_departure_coverage.png'
            prior_csv.write_bytes(b'previous verified csv')
            prior_png.write_bytes(b'previous verified image')
            audit.__file__ = str(root / 'scripts/analysis/build_monthly_quality_audit.py')
            with self.assertRaisesRegex(ValueError, 'Independent totals disagree'):
                audit.main()
            self.assertEqual(prior_csv.read_bytes(), b'previous verified csv')
            self.assertEqual(prior_png.read_bytes(), b'previous verified image')
            self.assertFalse(list(processed.glob('*.partial')))
            self.assertFalse(list(output.glob('*.partial')))


if __name__ == '__main__':
    unittest.main()
