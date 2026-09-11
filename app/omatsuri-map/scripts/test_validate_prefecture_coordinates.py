import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).with_name("validate_prefecture_coordinates.py")
SPEC = importlib.util.spec_from_file_location("coordinate_validator", MODULE_PATH)
coordinate_validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coordinate_validator)


FEATURES = [{
    "type": "Feature",
    "properties": {"nam_ja": "テスト県"},
    "geometry": {"type": "Polygon", "coordinates": [[
        [138, 34], [140, 34], [140, 36], [138, 36], [138, 34],
    ]]},
}]


class CoordinateValidatorTest(unittest.TestCase):
    def test_finds_containing_prefecture(self):
        self.assertEqual(coordinate_validator.containing_prefecture(139, 35, FEATURES), "テスト県")
        self.assertIsNone(coordinate_validator.containing_prefecture(141, 35, FEATURES))

    def test_uses_verified_venue_coordinates_and_records_source(self):
        rows = [{
            "latitude": 0, "longitude": 0,
            "venue": {"latitude": 35, "longitude": 139},
        }]
        result = coordinate_validator.apply_coordinate_prefectures(rows, FEATURES, "https://example.test/boundary")
        self.assertEqual(result[0]["coordinate_prefecture"], "テスト県")
        self.assertEqual(result[0]["coordinate_validation_source"], "https://example.test/boundary")


if __name__ == "__main__":
    unittest.main()
