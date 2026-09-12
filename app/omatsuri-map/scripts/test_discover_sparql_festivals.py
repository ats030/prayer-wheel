import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("discover_sparql_festivals.py")
SPEC = importlib.util.spec_from_file_location("sparql_festival_discovery", MODULE_PATH)
sparql_discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sparql_discovery)


def entity(latitude=None, longitude=None, venue=None, area=None, title=None,
           label_ja=None, label_en=None, description_ja=None):
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
    result = {"claims": claims, "labels": {}, "descriptions": {}, "sitelinks": {}}
    if title:
        result["sitelinks"]["jawiki"] = {"title": title}
    if label_ja:
        result["labels"]["ja"] = {"value": label_ja}
    if label_en:
        result["labels"]["en"] = {"value": label_en}
    if description_ja:
        result["descriptions"]["ja"] = {"value": description_ja}
    return result


class SparqlFestivalDiscoveryTest(unittest.TestCase):
    def test_coordinate_priority(self):
        places = {"QVENUE": entity(35, 139), "QAREA": entity(36, 140)}
        self.assertEqual(
            sparql_discovery.resolved_coordinate(entity(34, 138, "QVENUE", "QAREA"), places),
            (34, 138, "festival"),
        )
        self.assertEqual(
            sparql_discovery.resolved_coordinate(entity(venue="QVENUE", area="QAREA"), places),
            (35, 139, "venue"),
        )

    def test_build_candidates_requires_jawiki_title(self):
        entities = {
            "Q1": entity(35.6, 139.7, title="例祭", label_ja="例祭"),
            "Q2": entity(35.6, 139.7, label_ja="無題ジェイエー"),
        }
        features = [{"properties": {"nam_ja": "東京都"}, "geometry": {
            "type": "Polygon",
            "coordinates": [[[139.0, 35.0], [140.5, 35.0], [140.5, 36.0], [139.0, 36.0], [139.0, 35.0]]],
        }}]
        result = sparql_discovery.build_candidates(entities, {}, features, set())
        self.assertEqual([item["qid"] for item in result], ["Q1"])
        self.assertEqual(result[0]["prefecture"], "東京都")

    def test_build_candidates_excludes_venue_like_titles_and_existing_qids(self):
        entities = {
            "Q1": entity(35.6, 139.7, title="例神社", label_ja="例神社"),
            "Q2": entity(35.6, 139.7, title="既存祭", label_ja="既存祭"),
        }
        features = [{"properties": {"nam_ja": "東京都"}, "geometry": {
            "type": "Polygon",
            "coordinates": [[[139.0, 35.0], [140.5, 35.0], [140.5, 36.0], [139.0, 36.0], [139.0, 35.0]]],
        }}]
        result = sparql_discovery.build_candidates(entities, {}, features, {"Q2"})
        self.assertEqual(result, [])

    def test_build_candidates_excludes_out_of_prefecture_coordinates(self):
        entities = {
            "Q1": entity(0.0, 0.0, title="海外祭", label_ja="海外祭"),
        }
        result = sparql_discovery.build_candidates(entities, {}, [], set())
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
