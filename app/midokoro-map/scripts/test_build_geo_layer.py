#!/usr/bin/env python3
"""Geosites hide only when the shiseki tab already shows the same heritage."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("build_geo_layer", Path(__file__).with_name("build-geo-layer.py"))
layer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layer)


def cells(*rows):
    out = {}
    for site_id, label, lat, lon in rows:
        out.setdefault((round(lat * 100), round(lon * 100)), []).append((site_id, layer.normalize(label), lat, lon))
    return out


class ShownByShiseki(unittest.TestCase):
    def test_same_heritage_id_ignores_zero_padding(self):
        site = {"heritage_id": "00003511", "name": "下地島の通り池", "latitude": 24.8, "longitude": 125.1}
        self.assertEqual(layer.shown_by_shiseki(site, {"401/3511": "Q1"}, {}), "Q1")

    def test_same_name_nearby_is_shown(self):
        site = {"heritage_id": "1050", "name": "東尋坊", "latitude": 36.2373, "longitude": 136.1253}
        self.assertEqual(layer.shown_by_shiseki(site, {}, cells(("Q2", "東尋坊", 36.2375, 136.1255))), "Q2")

    def test_containing_name_is_another_heritage(self):
        site = {"heritage_id": "1424", "name": "石山寺硅灰石", "latitude": 34.9605, "longitude": 135.9058}
        self.assertIsNone(layer.shown_by_shiseki(site, {}, cells(("Q3", "石山寺", 34.9606, 135.9066))))

    def test_same_name_two_longitude_cells_away_is_shown(self):
        # 0.012 degree of longitude is about 980 m at 43°N but two 0.01 degree cells away.
        site = {"heritage_id": "2", "name": "オンネトー", "latitude": 43.3850, "longitude": 143.9640}
        self.assertEqual(layer.shown_by_shiseki(site, {}, cells(("Q5", "オンネトー", 43.3850, 143.9760))), "Q5")

    def test_same_name_far_away_is_another_place(self):
        site = {"heritage_id": "1", "name": "白糸ノ滝", "latitude": 35.31, "longitude": 138.59}
        self.assertIsNone(layer.shown_by_shiseki(site, {}, cells(("Q4", "白糸ノ滝", 36.35, 138.59))))


if __name__ == "__main__":
    unittest.main()
