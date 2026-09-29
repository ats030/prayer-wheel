import unittest

from fetch_shiseki import era_from_date, inception_era, row_era


class EraTest(unittest.TestCase):
    def test_year_precision_maps_to_era(self):
        self.assertEqual(era_from_date("+1609-01-01T00:00:00Z", 9), "江戸時代")
        self.assertEqual(era_from_date("+0603-01-01T00:00:00Z", 9), "飛鳥時代")
        self.assertEqual(era_from_date("+1998-05-01T00:00:00Z", 11), "平成時代")

    def test_before_asuka_is_not_derived(self):
        self.assertIsNone(era_from_date("-0003-01-01T00:00:00Z", 9))
        self.assertIsNone(era_from_date("+0401-01-01T00:00:00Z", 9))

    def test_century_within_one_era(self):
        # 9世紀(801〜900)は平安時代に収まる。両方の格納形式を受け付ける。
        self.assertEqual(era_from_date("+0900-00-00T00:00:00Z", 7), "平安時代")
        self.assertEqual(era_from_date("+0801-00-00T00:00:00Z", 7), "平安時代")

    def test_century_spanning_eras_is_skipped(self):
        # 16世紀は室町・安土桃山にまたがる
        self.assertIsNone(era_from_date("+1600-00-00T00:00:00Z", 7))
        self.assertIsNone(era_from_date("+1000-00-00T00:00:00Z", 6))

    def test_conflicting_inceptions_are_skipped(self):
        self.assertIsNone(inception_era([("+1609-01-01T00:00:00Z", 9), ("+1400-01-01T00:00:00Z", 9)]))
        self.assertEqual(inception_era([("+1609-01-01T00:00:00Z", 9), ("+1610-01-01T00:00:00Z", 9)]), "江戸時代")

    def test_kofun_type_fallback(self):
        self.assertEqual(row_era("Q1", {"types": ["前方後円墳・古墳"]}, {}), ("古墳時代", "kofun_type"))
        self.assertEqual(row_era("Q1", {"types": ["古墳"]}, {"Q1": [("+0650-01-01T00:00:00Z", 9)]}), ("飛鳥時代", "inception"))
        self.assertEqual(row_era("Q1", {"types": ["神社"]}, {}), ("", ""))


if __name__ == "__main__":
    unittest.main()
