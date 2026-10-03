from datetime import date
import importlib.util
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).parent))
MODULE_PATH = Path(__file__).with_name("apply_official_festivals.py")
SPEC = importlib.util.spec_from_file_location("official_festivals", MODULE_PATH)
official = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(official)

TODAY = date(2026, 10, 3)
SOURCE = "https://example.test/event"
KOCHI = [{
    "properties": {"nam_ja": "高知県"},
    "geometry": {"type": "Polygon", "coordinates": [[[133, 33], [134, 33], [134, 34], [133, 34], [133, 33]]]},
}]


def row(**overrides):
    value = {
        "qid": "local-kochi-test",
        "label_ja": "テスト花火祭り",
        "prefecture": "高知県",
        "latitude": 33.5,
        "longitude": 133.5,
        "description": "海上から花火が打ち上げられる。",
        "description_source": SOURCE,
        "coordinate_source": "official_venue",
        "venue": {
            "name": "テスト海岸",
            "latitude": 33.5,
            "longitude": 133.5,
            "source": SOURCE,
            "coordinate_source": SOURCE,
            "precision": "venue_area",
            "coordinate_note": "会場の代表点",
        },
        "lifecycle": {"status": "active", "source": SOURCE, "checked_on": "2026-10-03", "evidence": "2026年の開催案内"},
        "occurrences": [{"year": 2026, "start": "2026-08-01", "end": "2026-08-01", "status": "past", "source": SOURCE}],
    }
    value.update(overrides)
    return value


class OfficialFestivalsTest(unittest.TestCase):
    def test_local_id_is_added_with_derived_categories_idempotently(self):
        once = official.apply_batch([], [row()], KOCHI, TODAY)
        self.assertEqual(once[0]["qid"], "local-kochi-test")
        self.assertEqual(once[0]["categories"], ["花火"])
        self.assertEqual(once[0]["coordinate_prefecture"], "高知県")
        self.assertEqual(official.apply_batch(once, [row()], KOCHI, TODAY), once)

    def test_rejects_hand_written_categories(self):
        with self.assertRaisesRegex(ValueError, "categories are derived"):
            official.apply_batch([], [row(categories=["花火"])], KOCHI, TODAY)

    def test_rejects_same_name_under_another_id(self):
        once = official.apply_batch([], [row()], KOCHI, TODAY)
        with self.assertRaisesRegex(ValueError, "name already registered"):
            official.apply_batch(once, [row(qid="local-kochi-other")], KOCHI, TODAY)

    def test_rejects_venue_outside_prefecture(self):
        venue = dict(row()["venue"], latitude=35.0)
        with self.assertRaisesRegex(ValueError, "outside declared prefecture"):
            official.apply_batch([], [row(latitude=35.0, venue=venue)], KOCHI, TODAY)

    def test_rejects_stale_review(self):
        lifecycle = dict(row()["lifecycle"], checked_on="2026-08-01")
        with self.assertRaisesRegex(ValueError, "within the last 31 days"):
            official.apply_batch([], [row(lifecycle=lifecycle)], KOCHI, TODAY)


if __name__ == "__main__":
    unittest.main()
