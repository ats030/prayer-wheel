import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("import_wikimedia_festivals.py")
SPEC = importlib.util.spec_from_file_location("festival_import", MODULE_PATH)
festival_import = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(festival_import)


def entity(latitude=None, longitude=None, venue=None, area=None):
    claims = {}
    if latitude is not None:
        claims["P625"] = [{"mainsnak": {"datavalue": {"value": {
            "latitude": latitude, "longitude": longitude,
        }}}}]
    if venue:
        claims["P276"] = [{"mainsnak": {"datavalue": {"value": {
            "entity-type": "item", "id": venue,
        }}}}]
    if area:
        claims["P131"] = [{"mainsnak": {"datavalue": {"value": {
            "entity-type": "item", "id": area,
        }}}}]
    return {"claims": claims}


class FestivalImportTest(unittest.TestCase):
    def test_coordinate_priority(self):
        places = {"QVENUE": entity(35, 139), "QAREA": entity(36, 140)}
        self.assertEqual(
            festival_import.resolved_coordinate(entity(34, 138, "QVENUE", "QAREA"), places),
            (34, 138, "festival"),
        )
        self.assertEqual(
            festival_import.resolved_coordinate(entity(venue="QVENUE", area="QAREA"), places),
            (35, 139, "venue"),
        )

    def test_candidates_exclude_venues_duplicates_and_ambiguous_prefectures(self):
        titles = {
            "例祭": {"東京都"},
            "例神社 (東京)": {"東京都"},
            "広域祭": {"東京都", "埼玉県"},
            "既存祭": {"東京都"},
        }
        qids = {title: f"Q{index}" for index, title in enumerate(titles, 1)}
        entities = {
            qid: {**entity(35.6, 139.7), "labels": {}, "descriptions": {}}
            for qid in qids.values()
        }
        result = festival_import.build_candidates(titles, qids, entities, {}, {qids["既存祭"]})
        self.assertEqual([item["label_ja"] for item in result], ["例祭"])
        self.assertEqual(result[0]["coordinate_source"], "festival")


if __name__ == "__main__":
    unittest.main()
