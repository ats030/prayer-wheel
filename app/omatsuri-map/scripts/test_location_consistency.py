import json
from pathlib import Path
import unittest
from urllib.parse import urlparse


DATA_PATH = Path(__file__).parents[1] / "frontend" / "festivals.json"


def valid_web_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class LocationConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    def test_verified_venues_have_complete_coordinates_provenance_and_precision(self):
        for row in self.rows:
            venue = row.get("venue")
            if not venue:
                continue
            with self.subTest(qid=row.get("qid")):
                self.assertTrue(venue.get("name"))
                self.assertIsInstance(venue.get("latitude"), (int, float))
                self.assertIsInstance(venue.get("longitude"), (int, float))
                self.assertTrue(valid_web_url(venue.get("source")))
                self.assertTrue(valid_web_url(venue.get("coordinate_source")))
                self.assertIn(venue.get("precision"), {"exact", "venue_area"})

    def test_published_descriptions_share_the_verified_venue_source(self):
        for row in self.rows:
            source = row.get("description_source")
            if not source:
                continue
            with self.subTest(qid=row.get("qid")):
                self.assertTrue(row.get("description"))
                self.assertEqual(source, row.get("venue", {}).get("source"))


if __name__ == "__main__":
    unittest.main()
