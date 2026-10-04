import unittest

from fetch_shiseki import restore_jalan_metadata


class JalanMetadataTests(unittest.TestCase):
    def setUp(self):
        self.site = {"qid": "Q218813", "prefecture": "長野県", "latitude": 36.05,
                     "longitude": 138.09}
        self.areas = {"jalan_lrg_code": "161900", "jalan_lrg_name": "上諏訪・下諏訪・岡谷・霧ヶ峰・美ヶ原高原",
                      "jalan_sml_code": "161902", "jalan_sml_name": "上諏訪・下諏訪・岡谷・霧ヶ峰・美ヶ原高原"}

    def test_refresh_keeps_area_metadata_for_unchanged_site(self):
        rows = [dict(self.site, description="更新した概要")]
        result = restore_jalan_metadata(rows, [dict(self.site, **self.areas)])
        self.assertEqual(result[0]["description"], "更新した概要")
        for field, value in self.areas.items():
            self.assertEqual(result[0][field], value)

    def test_changed_locations_and_new_sites_require_reassignment(self):
        for change in ({"latitude": 36.1}, {"longitude": 138.2}, {"prefecture": "東京都"}, {"qid": "Q999"}):
            with self.subTest(change=change):
                result = restore_jalan_metadata([dict(self.site, **change)], [dict(self.site, **self.areas)])
                self.assertNotIn("jalan_lrg_code", result[0])

    def test_source_scoped_ids_are_preserved_without_a_qid(self):
        site = dict(self.site, id="bunka:401:1", qid="")
        result = restore_jalan_metadata([dict(site)], [dict(site, **self.areas)])
        self.assertEqual(result[0]["jalan_sml_code"], self.areas["jalan_sml_code"])

    def test_incomplete_old_assignments_are_not_reused(self):
        result = restore_jalan_metadata([dict(self.site)], [dict(self.site, jalan_lrg_code="161900")])
        self.assertNotIn("jalan_lrg_code", result[0])


if __name__ == "__main__":
    unittest.main()
