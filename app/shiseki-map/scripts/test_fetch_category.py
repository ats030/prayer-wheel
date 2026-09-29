import unittest

from fetch_shiseki import category


class CategoryTest(unittest.TestCase):
    def test_temple_in_station_or_bridge_name_is_not_religious(self):
        self.assertEqual(category(["歴史的建造物"], "岩水寺駅"), ["歴史的建造物"])
        self.assertEqual(category(["橋"], "久宝寺橋"), ["橋"])
        self.assertEqual(category(["橋"], "城光寺橋"), ["橋"])

    def test_religious_type_still_counts_for_facility_suffix(self):
        self.assertEqual(category(["仏教寺院"], "東本願寺真宗会館"), ["社寺・宗教遺跡"])

    def test_temple_name_without_facility_suffix_is_religious(self):
        self.assertEqual(category([], "世尊寺"), ["社寺・宗教遺跡"])


if __name__ == "__main__":
    unittest.main()
