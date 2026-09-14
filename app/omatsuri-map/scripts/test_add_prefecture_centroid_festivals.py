import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("add_prefecture_centroid_festivals.py")
SPEC = importlib.util.spec_from_file_location("centroid_import", MODULE_PATH)
centroid_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(centroid_import)


def make_entity(latitude=None, longitude=None):
    if latitude is None:
        return {"claims": {}}
    return {"claims": {"P625": [{"mainsnak": {"datavalue": {"value": {
        "latitude": latitude, "longitude": longitude,
    }}}}]}}


class CollectCategoryCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.centroid_table = {"東京都": (35.6, 139.7)}
        self.real_discover = centroid_import.im.discover_titles
        self.real_fetch_qids = centroid_import.im.fetch_qids
        self.real_fetch_entities = centroid_import.im.fetch_entities

        centroid_import.im.discover_titles = lambda session: {
            "単一県祭": {"東京都"},
            "広域祭": {"東京都", "埼玉県"},
            "既存祭": {"東京都"},
            "外れ神社": {"東京都"},
            "座標持ち祭": {"東京都"},
            "別単一県祭": {"東京都"},
        }
        centroid_import.im.fetch_qids = lambda session, titles: {
            "単一県祭": "Q1", "広域祭": "Q2", "既存祭": "Q3",
            "外れ神社": "Q4", "座標持ち祭": "Q5", "別単一県祭": "Q6",
        }
        centroid_import.im.fetch_entities = lambda session, qids: {
            "Q1": make_entity(), "Q2": make_entity(), "Q3": make_entity(),
            "Q4": make_entity(), "Q5": make_entity(35.6, 139.7), "Q6": make_entity(),
        }

    def tearDown(self):
        centroid_import.im.discover_titles = self.real_discover
        centroid_import.im.fetch_qids = self.real_fetch_qids
        centroid_import.im.fetch_entities = self.real_fetch_entities

    def test_collects_only_single_prefecture_uncord_and_new(self):
        existing_qids = {"Q3"}
        existing_titles = set()
        result = centroid_import.collect_category_candidates(
            None, self.centroid_table, existing_qids, existing_titles,
        )
        self.assertCountEqual(result.keys(), ["Q1", "Q6"])
        self.assertNotIn("Q2", result)  # multi-prefecture excluded
        self.assertNotIn("Q3", result)  # existing qid excluded
        self.assertNotIn("Q4", result)  # EXCLUDED_TITLE excluded
        self.assertNotIn("Q5", result)  # already geolocated excluded

    def test_category_row_uses_category_prefecture_and_centroid(self):
        result = centroid_import.collect_category_candidates(
            None, {"東京都": (35.6, 139.7)}, set(), set(),
        )
        row = result["Q1"]
        self.assertEqual(row["prefecture"], "東京都")
        self.assertEqual((row["latitude"], row["longitude"]), (35.6, 139.7))
        self.assertEqual(row["coordinate_source"], "prefecture_centroid")
        self.assertEqual(row["label_ja"], "単一県祭")


if __name__ == "__main__":
    unittest.main()
