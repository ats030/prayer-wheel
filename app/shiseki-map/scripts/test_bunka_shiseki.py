import unittest

from bunka_shiseki import components, designation_of, find_match, join_kinds, merge_bunka, merge_meisho, normalize, p4275_map, same_place, similar
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

    def test_meisho_on_a_designated_shiseki_keeps_one_row_with_both_labels(self):
        shiseki = {**row("毛越寺境内", lat=38.98, lon=141.11, pref="岩手県"), "designation": "special",
                   "designation_label": "特別史跡", "designation_source": "s", "heritage_id": "401/100",
                   "categories": ["社寺・宗教遺跡"]}
        dual = item(heritage="100", name="毛越寺庭園", pref="岩手県", lat="38.98", lon="141.11",
                    kind1="特別史跡", kind2="特別名勝")
        rows, stats = merge_meisho([shiseki], [dual], {}, category)
        self.assertEqual(len(rows), 1)
        self.assertEqual(shiseki["designation_label"], "特別史跡・特別名勝")
        self.assertEqual(shiseki["designation_source"], "s")
        self.assertEqual(shiseki["categories"], ["社寺・宗教遺跡", "名勝"])
        self.assertEqual(stats["heritage_id"], 1)

    def test_meisho_on_an_undesignated_row_takes_the_meisho_source(self):
        temple = {**row("天龍寺", pref="京都府", lat=35.0157, lon=135.6737), "designation_label": "", "categories": ["社寺・宗教遺跡"]}
        rows, stats = merge_meisho([temple], [item(heritage="200", name="天龍寺庭園", pref="京都府", lat="35.0158",
                                                   lon="135.6738", kind1="史跡", kind2="特別名勝")], {}, category)
        self.assertEqual(len(rows), 1)
        self.assertEqual((temple["designation"], temple["designation_label"]), ("special", "史跡・特別名勝"))
        self.assertEqual(temple["designation_source"], "https://kunishitei.bunka.go.jp/heritage/detail/401/200")
        self.assertIn("名勝", temple["categories"])
        self.assertEqual(stats["near"], 1)

    def test_new_meisho_row_has_source_category_and_components(self):
        rows, stats = merge_meisho([], [
            item(heritage="300", name="大和三山\n\u3000香具山\n\u3000畝傍山\n\u3000耳成山", pref="奈良県",
                 lat="34.49", lon="135.80", kind1="名勝"),
            item(heritage="301", name="六義園", pref="東京都", lat="35.73", lon="139.74", kind1="特別名勝"),
            item(heritage="302", name="座標なし", lat="", lon="", kind1="名勝")], {}, category)
        sanzan, garden = rows
        self.assertEqual((sanzan["id"], sanzan["label_ja"]), ("bunka:401:300", "大和三山"))
        self.assertEqual(sanzan["description"], "構成: 香具山、畝傍山、耳成山")
        self.assertEqual((sanzan["designation"], sanzan["designation_label"]), ("national", "名勝"))
        self.assertEqual(sanzan["categories"], ["名勝"])
        self.assertEqual(sanzan["source_url"], "https://kunishitei.bunka.go.jp/heritage/detail/401/300")
        self.assertEqual((garden["designation"], garden["designation_label"]), ("special", "特別名勝"))
        self.assertEqual((stats["added"], stats["no_coordinates"]), (2, 1))

    def test_same_place_rejects_a_facility_inside_the_meisho_and_garden_only_overlap(self):
        self.assertFalse(same_place("室戸岬", "室戸岬灯台", "near"))
        self.assertTrue(same_place("円通寺庭園", "円通寺", "near"))
        self.assertTrue(same_place("鳳来寺山", "鳳来寺", "near"))
        self.assertTrue(same_place("仙巌園", "仙巌園 (鹿児島市)", "near"))
        self.assertFalse(same_place("安養院庭園", "太山寺成就院庭園", "close"))

    def test_join_kinds_is_order_independent_and_keeps_the_higher_kind(self):
        self.assertEqual(join_kinds(join_kinds("国指定史跡", ["名勝"]), ["特別名勝"]), "国指定史跡・特別名勝")
        self.assertEqual(join_kinds(join_kinds("国指定史跡", ["特別名勝"]), ["名勝"]), "国指定史跡・特別名勝")
        self.assertEqual(join_kinds("国指定史跡", ["史跡", "名勝"]), "国指定史跡・名勝")
        self.assertEqual(join_kinds("国指定史跡", ["特別史跡", "特別名勝"]), "特別史跡・特別名勝")
        self.assertEqual(join_kinds("登録有形文化財", ["名勝"]), "登録有形文化財・名勝")

    def test_special_natural_monument_does_not_make_a_meisho_special(self):
        rows, _ = merge_meisho([], [item(heritage="400", name="名勝X", kind1="名勝", kind2="特別天然記念物")], {}, category)
        self.assertEqual(rows[0]["designation"], "national")

    def test_raised_designation_points_to_the_meisho_record(self):
        shiseki = {**row("毛越寺", lat=38.98, lon=141.11, pref="岩手県"), "designation": "national",
                   "designation_label": "国指定史跡", "designation_source": "s", "heritage_id": "401/100",
                   "categories": []}
        merge_meisho([shiseki], [item(heritage="101", name="毛越寺庭園", pref="岩手県", lat="38.98", lon="141.11",
                                      kind1="特別名勝")], {}, category)
        self.assertEqual((shiseki["designation"], shiseki["heritage_id"]), ("special", "401/101"))
        self.assertEqual(shiseki["designation_source"], "https://kunishitei.bunka.go.jp/heritage/detail/401/101")

    def test_zero_padded_ids_keep_the_padding_in_urls_but_not_in_ids(self):
        rows, _ = merge_bunka([], [item(heritage="00003948", name="ゼロ詰め史跡")], {}, category)
        self.assertEqual(rows[0]["source_url"], "https://kunishitei.bunka.go.jp/heritage/detail/401/00003948")
        self.assertEqual(rows[0]["designation_source"], "https://kunishitei.bunka.go.jp/heritage/detail/401/00003948")
        self.assertEqual((rows[0]["heritage_id"], rows[0]["id"]), ("401/3948", "bunka:401:3948"))

    def test_zero_padded_meisho_keeps_the_padding_in_urls(self):
        rows, _ = merge_meisho([], [item(heritage="00003449", name="ゼロ詰め名勝", kind1="名勝")], {}, category)
        self.assertEqual(rows[0]["source_url"], "https://kunishitei.bunka.go.jp/heritage/detail/401/00003449")
        self.assertEqual((rows[0]["heritage_id"], rows[0]["id"]), ("401/3449", "bunka:401:3449"))

    def test_components_reads_lines_after_the_name(self):
        self.assertEqual(components("黒部峡谷\n\u3000附\u3000猿飛並びに奥鐘山"), ["附 猿飛並びに奥鐘山"])
        self.assertEqual(components("六義園"), [])


if __name__ == "__main__":
    unittest.main()
