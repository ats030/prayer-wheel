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

    def test_castle_and_bridge_fields(self):
        fields = infobox_fields("{{日本の城郭概要表\n|build_y = [[天正]]10年（[[1582年]]）\n}}")
        self.assertEqual(fields, {"build_y": "天正10年（1582年）"})
        self.assertEqual(fields_era(fields, era_of_year), ("安土桃山時代", "build_y"))
        fields = infobox_fields("{{橋\n|建設 = [[1979年]]（[[昭和]]54年）\n|建設年 = x\n}}")
        self.assertEqual(fields_era(fields, era_of_year), ("昭和時代", "建設"))
        self.assertIsNone(era("初代：1920年、現橋：1985年"))
        fields = infobox_fields("{{橋\n|建設 = [[三菱重工業]]\n|竣工 = 1998年\n}}")
        self.assertEqual(fields["建設"], "三菱重工業")
        self.assertEqual(fields_era(fields, era_of_year), ("平成時代", "竣工"))

    def test_gengo_only_values(self):
        self.assertEqual(era("宝永2年"), "江戸時代")
        self.assertEqual(era("天平九年"), "奈良時代")
        self.assertEqual(era("寛永元（1624）年"), "江戸時代")
        self.assertEqual(era("弘仁年間（810–824）"), "平安時代")
        self.assertEqual(era("天正年間"), "安土桃山時代")
        self.assertEqual(era("正平3年"), "室町時代")
        self.assertEqual(era("慶応4年"), "江戸時代")
        self.assertEqual(era("明治元年"), "明治時代")

    def test_gengo_values_spanning_eras_or_out_of_range_are_rejected(self):
        self.assertIsNone(era("慶長年間"))
        self.assertIsNone(era("天平二十三年"))
        self.assertIsNone(era("明応4年（1945年）"))
        self.assertIsNone(era("元亀・天正年間"))
        self.assertIsNone(era("永享年間か"))
        self.assertEqual(era("永正年間（1504年から1521年）"), "室町時代")
        self.assertEqual(era("1900年着工、3年かけて完成"), "明治時代")
        self.assertIsNone(era("白雉30年"))
        self.assertIsNone(era("未詳（開山は応永年間）"))


if __name__ == "__main__":
    unittest.main()
