import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).with_name("apply_verified_occurrences.py")
SPEC = importlib.util.spec_from_file_location("verified_occurrences", MODULE_PATH)
verified_occurrences = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verified_occurrences)


class VerifiedOccurrencesTest(unittest.TestCase):
    def test_merges_idempotently_and_uses_latest_date(self):
        rows = [{"qid": "Q1", "date": "日付未定"}]
        verified = {"Q1": [
            {"year": 2026, "start": "2026-01-02", "end": "2026-01-03", "source": "https://example.test/2026"},
            {"year": 2027, "start": "2027-02-04", "end": "2027-02-04", "source": "https://example.test/2027"},
        ]}
        once = verified_occurrences.apply_occurrences(rows, verified)
        twice = verified_occurrences.apply_occurrences(once, verified)
        self.assertEqual(len(twice[0]["occurrences"]), 2)
        self.assertEqual(twice[0]["date"], "2027-02-04")

    def test_missing_qid_fails(self):
        with self.assertRaisesRegex(ValueError, "QID not found"):
            verified_occurrences.apply_occurrences([], {"Q404": []})

    def test_matsudo_fireworks_uses_official_2026_date(self):
        rows = [{"qid": "Q132860355", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q132860355": verified_occurrences.VERIFIED_OCCURRENCES["Q132860355"]}
        )
        self.assertEqual(result[0]["date"], "2026-08-01")
        self.assertEqual(result[0]["occurrences"][0]["source"], "https://matsudo-hanabi.com/")

    def test_nagasaki_kunchi_uses_official_2026_scheduled_date(self):
        rows = [{"qid": "Q114712", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q114712": verified_occurrences.VERIFIED_OCCURRENCES["Q114712"]}
        )
        self.assertEqual(result[0]["date"], "2026-10-07〜2026-10-09")
        self.assertEqual(result[0]["occurrences"][0]["status"], "scheduled")
        self.assertEqual(result[0]["occurrences"][0]["source"], "https://nagasaki-kunchi.com/")

    def test_karatsu_kunchi_uses_official_fixed_date_rule(self):
        rows = [{"qid": "Q493695", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q493695": verified_occurrences.VERIFIED_OCCURRENCES["Q493695"]}
        )
        self.assertEqual(result[0]["date"], "2026-11-02〜2026-11-04")
        self.assertEqual(result[0]["occurrences"][0]["source"], "https://www.city.karatsu.lg.jp/page/4344.html")

    def test_tiff_uses_official_2026_scheduled_date(self):
        rows = [{"qid": "Q1043431", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q1043431": verified_occurrences.VERIFIED_OCCURRENCES["Q1043431"]}
        )
        self.assertEqual(result[0]["date"], "2026-10-26〜2026-11-04")
        self.assertEqual(result[0]["occurrences"][0]["status"], "scheduled")

    def test_fuji_rock_uses_official_2026_date(self):
        rows = [{"qid": "Q1151186", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q1151186": verified_occurrences.VERIFIED_OCCURRENCES["Q1151186"]}
        )
        self.assertEqual(result[0]["date"], "2026-07-24〜2026-07-26")

    def test_hokkai_soran_uses_official_single_day_date(self):
        rows = [{"qid": "Q11402392", "date": "日付未定"}]
        result = verified_occurrences.apply_occurrences(
            rows, {"Q11402392": verified_occurrences.VERIFIED_OCCURRENCES["Q11402392"]}
        )
        self.assertEqual(result[0]["date"], "2026-08-09")


if __name__ == "__main__":
    unittest.main()
