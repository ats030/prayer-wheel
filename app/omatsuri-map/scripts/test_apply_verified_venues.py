import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("apply_verified_venues.py")
SPEC = importlib.util.spec_from_file_location("verified_venues", MODULE_PATH)
verified_venues = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verified_venues)


class VerifiedVenuesTest(unittest.TestCase):
    def test_applies_grounded_venue_and_description_idempotently(self):
        rows = [{"qid": "Q132860355", "description": "old"}]
        twice = verified_venues.apply_venues(verified_venues.apply_venues(rows))
        self.assertEqual(twice[0]["venue"]["name"], "古ケ崎河川敷スポーツ広場")
        self.assertEqual(twice[0]["venue"]["precision"], "venue_area")
        self.assertEqual(twice[0]["description_source"], "https://matsudo-hanabi.com/")

    def test_rejects_venue_without_coordinate_source(self):
        with self.assertRaisesRegex(ValueError, "venue sources are required"):
            verified_venues.apply_venues(
                [{"qid": "Q1"}],
                {"Q1": {"name": "会場", "source": "https://example.test", "precision": "exact"}},
                {},
            )

    def test_missing_qid_fails(self):
        with self.assertRaisesRegex(ValueError, "QID not found"):
            verified_venues.apply_venues([], {"Q404": {}}, {})


if __name__ == "__main__":
    unittest.main()
