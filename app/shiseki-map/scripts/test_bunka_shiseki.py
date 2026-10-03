import unittest

from bunka_shiseki import designation_of, find_match, merge_bunka, normalize, p4275_map, similar
from fetch_shiseki import category


def item(heritage="1260", name="関ヶ原古戦場", pref="岐阜県", lat="35.37", lon="136.46", kind1="史跡", kind2=""):
    return {"管理対象ID": heritage, "名称": name, "都道府県": pref, "所在地": "不破郡関ケ原町",
            "緯度": lat, "経度": lon, "種別1": kind1, "種別2": kind2}


def row(label, pref="岐阜県", lat=35.37, lon=136.46, qid="Q1"):
    return {"qid": qid, "label_ja": label, "title_ja": label, "prefecture": pref,
            "latitude": lat, "longitude": lon, "designation": "undesig"}


class BunkaShisekiTest(unittest.TestCase):
    def test_normalize_drops_parentheses_spaces_and_dots(self):
        self.assertEqual(normalize("法華堂跡 (源頼朝墓・北条義時墓)"), "法華堂跡")
        self.assertEqual(normalize("柳之御所・平泉遺跡群"), "柳之御所平泉遺跡群")

    def test_designation_reads_both_kind_columns(self):
        self.assertEqual(designation_of(item(kind1="特別史跡")), "special")
        self.assertEqual(designation_of(item(kind1="特別名勝", kind2="特別史跡")), "special")
        self.assertEqual(designation_of(item()), "national")

    def test_p4275_map_strips_zero_padding(self):
        bindings = [{"id": {"value": "401/00003892"}, "item": {"value": "http://www.wikidata.org/entity/Q42"}},
                    {"id": {"value": "401/abc"}, "item": {"value": "http://www.wikidata.org/entity/Q43"}}]
        self.assertEqual(p4275_map(bindings), {"3892": ["Q42"]})

    def test_similar_rejects_group_member_and_nearby_shrine(self):
        self.assertFalse(similar("大野原古墳群", "椀貸塚古墳"))
        self.assertFalse(similar("吉志部瓦窯跡", "吉志部神社"))
        self.assertFalse(similar("大村家墓所", "本経寺 (大村市)"))
        self.assertTrue(similar("大宰府跡", "Dazaifu ruins"))
        self.assertTrue(similar("多賀城跡附寺跡", "多賀城廃寺跡"))

    def test_find_match_prefers_p4275_then_name_then_near(self):
        by_qid, wrong_name, exact = row("別名", qid="Q9"), row("箕輪城", qid="Q2"), row("関ヶ原古戦場", qid="Q3")
        rows = [by_qid, wrong_name, exact]
        self.assertEqual(find_match(item(), "関ヶ原古戦場", {"Q9": by_qid}, rows, ["Q9"]), (by_qid, "p4275"))
        self.assertEqual(find_match(item(), "関ヶ原古戦場", {}, rows, []), (exact, "name"))
        self.assertEqual(find_match(item(name="箕輪城跡"), "箕輪城跡", {}, rows, []), (wrong_name, "near"))
        far = row("箕輪城", lat=36.0, qid="Q4")
        self.assertEqual(find_match(item(), "箕輪城跡", {}, [far], []), (None, "none"))

    def test_find_match_ignores_other_prefecture(self):
        other = row("関ヶ原古戦場", pref="滋賀県")
        self.assertEqual(find_match(item(), "関ヶ原古戦場", {}, [other], []), (None, "none"))

    def test_merge_marks_matches_and_adds_unmatched_rows(self):
        existing = row("Sekigahara", qid="Q5")
        rows, stats = merge_bunka([existing], [item(), item(heritage="1432", name="桶狭間古戦場伝説地", pref="愛知県"),
                                               item(heritage="9", name="座標なし", lat="", lon="")],
                                  {"1260": ["Q5"]}, category)
        self.assertEqual(existing["label_ja"], "関ヶ原古戦場")
        self.assertEqual(existing["designation"], "national")
        self.assertEqual(existing["heritage_id"], "401/1260")
        added = rows[-1]
        self.assertEqual(added["id"], "bunka:401:1432")
        self.assertNotIn("qid", added)
        self.assertEqual(added["source_url"], "https://kunishitei.bunka.go.jp/heritage/detail/401/1432")
        self.assertEqual((stats["p4275"], stats["added"], stats["no_coordinates"]), (1, 1, 1))

    def test_p4275_match_requires_same_prefecture_or_nearby_row(self):
        gunma = row("八幡山古墳", pref="群馬県", lat=36.3, lon=139.0, qid="Q7")
        self.assertEqual(find_match(item(name="八幡山古墳", pref="愛知県"), "八幡山古墳", {"Q7": gunma}, [gunma], ["Q7"]),
                         (None, "none"))
        border = row("関ヶ原古戦場", pref="滋賀県", qid="Q8")
        self.assertEqual(find_match(item(), "関ヶ原古戦場", {"Q8": border}, [border], ["Q8"]), (border, "p4275"))

    def test_shared_row_keeps_the_higher_designation(self):
        existing = row("慈照寺", qid="Q6")
        merge_bunka([existing], [item(heritage="1", name="慈照寺旧境内"),
                                 item(heritage="2", name="慈照寺庭園", kind1="特別史跡")], {"1": ["Q6"], "2": ["Q6"]}, category)
        self.assertEqual((existing["designation"], existing["heritage_id"]), ("special", "401/2"))

    def test_blank_prefecture_is_located_from_coordinates(self):
        crossing = {**item(heritage="3542", name="智頭往来", pref=""), "所在地": "鳥取県八頭郡智頭町、岡山県英田郡西粟倉村"}
        rows, _ = merge_bunka([], [crossing], {}, category,
                              lambda lat, lon: "鳥取県")
        self.assertEqual(rows[0]["prefecture"], "鳥取県")
        self.assertEqual(rows[0]["address"], "鳥取県八頭郡智頭町、岡山県英田郡西粟倉村")


if __name__ == "__main__":
    unittest.main()
