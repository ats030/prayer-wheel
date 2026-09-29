import unittest

from fetch_shiseki import era_of_year
from infobox_era import fields_era, infobox_fields, value_era


def era(value):
    return value_era(value, era_of_year)


class InfoboxEraTest(unittest.TestCase):
    def test_year_in_wikilink(self):
        fields = infobox_fields("{{日本の寺院\n| 創建年 = [[延宝]]4年（[[1676年]]）<ref>x</ref>\n}}")
        self.assertEqual(fields, {"創建年": "延宝4年（1676年）"})
        self.assertEqual(fields_era(fields, era_of_year), ("江戸時代", "創建年"))

    def test_range_within_one_era(self):
        self.assertEqual(era("寛永年間（1624年 - 1645年"), "江戸時代")
        self.assertIsNone(era("1590年 - 1610年"))

    def test_explicit_era_word(self):
        self.assertEqual(era("室町時代の応永年間"), "室町時代")
        self.assertEqual(era("南北朝時代"), "室町時代")

    def test_uncertain_values_are_rejected(self):
        self.assertIsNone(era("（伝）敏達天皇11年（586年）"))
        self.assertIsNone(era("永正3年（1506年）?"))
        self.assertIsNone(era("天正12年(1584年)以前"))
        self.assertIsNone(era("不詳"))
        self.assertIsNone(era("天平年間"))
        self.assertIsNone(era("戦国時代末期"))

    def test_gengo_decides_transition_year(self):
        self.assertEqual(era("大正15年（1926年）"), "大正時代")
        self.assertEqual(era("1989年（平成元年）"), "平成時代")
        self.assertEqual(era("慶応4年（1868年）"), "江戸時代")
        self.assertIsNone(era("2019年"))

    def test_approximate_years_are_rejected(self):
        self.assertIsNone(era("1600年頃"))
        self.assertIsNone(era("慶長5年（1600年）ごろ"))
        self.assertIsNone(era("1960年代"))

    def test_pre_asuka_year_is_not_converted(self):
        self.assertIsNone(era("500年"))

    def test_first_present_field_decides(self):
        fields = {"創建": "不詳", "竣工": "1900年"}
        self.assertIsNone(fields_era(fields, era_of_year))
        self.assertEqual(fields_era({"竣工": "1996年（平成8年）"}, era_of_year), ("平成時代", "竣工"))


if __name__ == "__main__":
    unittest.main()
