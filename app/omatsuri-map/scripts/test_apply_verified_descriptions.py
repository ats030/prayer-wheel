import importlib.util
import json
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS))
MODULE_PATH = SCRIPTS / "apply_verified_descriptions.py"
SPEC = importlib.util.spec_from_file_location("verified_descriptions", MODULE_PATH)
verified_descriptions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verified_descriptions)

SOURCE = "https://example.test/festival"


def entry(**overrides):
    value = {
        "status": "active",
        "description": "出典に書かれた説明",
        "source": SOURCE,
        "venue": {"name": "会場", "address": "北海道某市"},
        "occurrences": [{"year": 2026, "start": "2026-08-01", "end": "2026-08-02"}],
    }
    value.update(overrides)
    return value


class VerifiedDescriptionsTest(unittest.TestCase):
    def test_applies_grounded_description_idempotently(self):
        rows = [{"qid": "Q1", "description": "", "date": "日付未定"}]
        verified = {"Q1": entry()}
        once = verified_descriptions.apply_descriptions(json.loads(json.dumps(rows)), verified)
        twice = verified_descriptions.apply_descriptions(json.loads(json.dumps(once)), verified)
        self.assertEqual(once, twice)
        row = twice[0]
        self.assertEqual(row["description_source"], row["venue"]["source"])
        self.assertEqual(row["occurrences"][0]["source"], SOURCE)
        self.assertEqual(row["venue"]["address"], "北海道某市")
        self.assertNotEqual(row["date"], "日付未定")

    def test_venue_point_keeps_coordinate_source(self):
        venue = {"name": "会場", "latitude": 43.0, "longitude": 141.0, "coordinate_source": "https://nominatim.test/"}
        rows = verified_descriptions.apply_descriptions([{"qid": "Q1"}], {"Q1": entry(venue=venue)})
        self.assertEqual(rows[0]["venue"]["precision"], "venue_area")
        self.assertEqual(rows[0]["venue"]["coordinate_source"], "https://nominatim.test/")

    def test_rejects_point_without_coordinate_source(self):
        venue = {"name": "会場", "latitude": 43.0, "longitude": 141.0}
        with self.assertRaisesRegex(ValueError, "coordinate source is required"):
            verified_descriptions.apply_descriptions([{"qid": "Q1"}], {"Q1": entry(venue=venue)})

    def test_rejects_ended_festival_without_last_occurrence(self):
        with self.assertRaisesRegex(ValueError, "ended festival"):
            verified_descriptions.apply_descriptions(
                [{"qid": "Q1"}], {"Q1": entry(status="ended", occurrences=[])}
            )

    def test_missing_qid_fails(self):
        with self.assertRaisesRegex(ValueError, "QID not found"):
            verified_descriptions.apply_descriptions([], {"Q404": entry()})

    def test_committed_data_is_valid(self):
        path = SCRIPTS.parent / "data/verified-descriptions.json"
        for qid, value in json.loads(path.read_text(encoding="utf-8")).items():
            verified_descriptions.validate(qid, value)


if __name__ == "__main__":
    unittest.main()
