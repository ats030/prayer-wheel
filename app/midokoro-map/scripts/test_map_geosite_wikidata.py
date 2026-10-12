#!/usr/bin/env python3
"""Natural monuments map to Wikidata by exact P4275, then to same-name Wikipedia articles."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("map_geosite_wikidata", Path(__file__).with_name("map-geosite-wikidata.py"))
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)

DETAIL = "https://kunishitei.bunka.go.jp/heritage/detail/"


def feature(number, name):
    return {"properties": {"name": name, "source_url": DETAIL + "401/" + number}}


def binding(qid, heritage, article=None):
    row = {"item": {"value": "http://www.wikidata.org/entity/" + qid}, "id": {"value": heritage}}
    if article:
        row["article"] = {"value": "https://ja.wikipedia.org/wiki/" + article}
    return row


class HeritageKey(unittest.TestCase):
    def test_reads_category_and_number(self):
        self.assertEqual(mapping.heritage_key(DETAIL + "401/00003511"), "401/00003511")
        self.assertIsNone(mapping.heritage_key("https://example.com/"))


class MatchP4275(unittest.TestCase):
    def test_exact_key_with_decoded_title(self):
        result = mapping.match_p4275([feature("00003511", "下地島の通り池")],
                                     [binding("Q1", "401/00003511", "%E9%80%9A%E3%82%8A%E6%B1%A0_(%E4%B8%8B%E5%9C%B0%E5%B3%B6)")])
        self.assertEqual(result, {"401/00003511": {"qid": "Q1", "title": "通り池 (下地島)", "via": "p4275"}})

    def test_item_without_article_keeps_qid(self):
        result = mapping.match_p4275([feature("1", "A")], [binding("Q2", "401/1")])
        self.assertEqual(result, {"401/1": {"qid": "Q2", "title": None, "via": "p4275"}})

    def test_other_category_or_unlisted_number_is_ignored(self):
        result = mapping.match_p4275([feature("1", "A")], [binding("Q3", "201/1"), binding("Q4", "401/2")])
        self.assertEqual(result, {})

    def test_duplicate_rows_for_one_item_are_fine(self):
        result = mapping.match_p4275([feature("1", "A")], [binding("Q5", "401/1", "A"), binding("Q5", "401/1", "A")])
        self.assertEqual(result["401/1"]["qid"], "Q5")

    def test_key_bound_to_two_items_is_left_out(self):
        result = mapping.match_p4275([feature("1", "A")], [binding("Q6", "401/1"), binding("Q7", "401/1")])
        self.assertEqual(result, {})


class TitleCandidates(unittest.TestCase):
    def test_unmatched_name_with_article_is_proposed(self):
        pages = {"玄武洞": {"title": "玄武洞", "pageprops": {"wikibase_item": "Q8"}}}
        result = mapping.title_candidates([feature("9", "玄武洞")], {}, pages)
        self.assertEqual(result, {"401/9": {"qid": "Q8", "title": "玄武洞", "via": "title"}})

    def test_redirected_title_is_used(self):
        pages = {"旧名": {"title": "新名", "pageprops": {"wikibase_item": "Q9"}}}
        self.assertEqual(mapping.title_candidates([feature("9", "旧名")], {}, pages)["401/9"]["title"], "新名")

    def test_matched_missing_disambiguation_and_itemless_pages_are_skipped(self):
        features = [feature("1", "A"), feature("2", "B"), feature("3", "C"), feature("4", "D"), feature("5", "E")]
        pages = {"A": {"title": "A", "pageprops": {"wikibase_item": "Q1"}},
                 "B": {"title": "B", "missing": True},
                 "C": {"title": "C", "pageprops": {"wikibase_item": "Q3", "disambiguation": ""}},
                 "D": {"title": "D", "pageprops": {}}}
        matched = {"401/1": {"qid": "Q1", "title": "A", "via": "p4275"}}
        self.assertEqual(mapping.title_candidates(features, matched, pages), {})


if __name__ == "__main__":
    unittest.main()
