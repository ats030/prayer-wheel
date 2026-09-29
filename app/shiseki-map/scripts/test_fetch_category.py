import unittest

from fetch_shiseki import category


class CategoryTest(unittest.TestCase):
    def test_temple_in_station_or_bridge_name_is_not_religious(self):
        self.assertEqual(category(["歴史的建造物"], "岩水寺駅"), ["歴史的建造物"])
        self.assertEqual(category(["橋"], "久宝寺橋"), ["橋"])
        self.assertEqual(category(["橋"], "城光寺橋"), ["橋"])

    def test_place_name_in_kofun_name_is_not_category(self):
        self.assertEqual(category(["前方後円墳"], "前橋二子山古墳"), ["古墳"])
        self.assertEqual(category(["古墳"], "寺山古墳群"), ["古墳"])
        self.assertEqual(category(["産業遺産"], "寺山炭窯跡"), ["産業遺産"])

    def test_place_name_bridge_kanji_is_not_bridge(self):
        self.assertEqual(category(["城"], "前橋城"), ["城跡"])
        self.assertEqual(category(["神社"], "熊野神社 (船橋市)"), ["社寺・宗教遺跡"])
        self.assertEqual(category([], "栗橋宿"), ["その他"])
        self.assertEqual(category([], "橋野高炉跡"), ["産業遺産", "遺跡"])

    def test_disambiguated_bridge_name_is_bridge(self):
        self.assertEqual(category([], "五月橋 (名張川)"), ["橋"])
        self.assertEqual(category([], "末広橋梁"), ["橋"])
        self.assertEqual(category([], "神流川橋「旧路線」"), ["橋"])

    def test_industrial_heritage_follows_bridge(self):
        self.assertEqual(category(["産業遺産"], "蹴上発電所"), ["産業遺産"])
        self.assertEqual(category(["産業遺産"], "勝鬨橋"), ["橋", "産業遺産"])
        self.assertEqual(category(["城", "産業遺産"], "萩城"), ["城跡", "産業遺産"])
        self.assertEqual(category(["灯台", "歴史的建造物", "産業遺産"], "大王埼灯台"), ["産業遺産", "歴史的建造物"])

    def test_bridge_suffix_still_counts_without_bridge_type(self):
        self.assertEqual(category(["歴史的建造物"], "眼鏡橋"), ["橋", "歴史的建造物"])

    def test_religious_type_still_counts_for_facility_suffix(self):
        self.assertEqual(category(["仏教寺院"], "東本願寺真宗会館"), ["社寺・宗教遺跡"])

    def test_temple_name_without_facility_suffix_is_religious(self):
        self.assertEqual(category([], "世尊寺"), ["社寺・宗教遺跡"])


if __name__ == "__main__":
    unittest.main()
