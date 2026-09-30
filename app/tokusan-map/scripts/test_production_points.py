import copy
import json
import unittest
from import_production_points import ROOT, apply_points, explicitly_prefecture_wide, first_municipality, first_place


class ProductionPointsTest(unittest.TestCase):
    def test_source_order_is_not_geographic_or_alphabetical_order(self):
        self.assertEqual(first_municipality('愛知県豊橋市、豊川市、新城市',
                                           ['新城市', '豊川市', '豊橋市']), '豊橋市')
        self.assertIsNone(first_municipality('愛知県', ['豊橋市']))

    def test_kangxi_radicals_match_ordinary_kanji(self):
        self.assertEqual(first_municipality('島根県⼤⽥市三瓶町', ['大田市']), '大田市')

    def test_explicit_whole_prefecture_survives_municipality_examples(self):
        for text in ['県内全域（白石市）', '米沢市、山形県全域', '鹿島市、全域', '県内全域']:
            self.assertTrue(explicitly_prefecture_wide(text, '山形県'), text)
        self.assertFalse(explicitly_prefecture_wide('山形県', '山形県'))
        self.assertFalse(explicitly_prefecture_wide('山形県米沢市', '山形県'))

    def test_catalog_golden_and_unchanged_evidence(self):
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        result = apply_points(items, registry)
        flower = next(x for x in result if x['label'] == '豊橋花穂')
        self.assertEqual(flower['city'], '豊橋市')
        self.assertAlmostEqual(flower['lat'], 34.769199)
        self.assertAlmostEqual(flower['lng'], 137.391469)
        self.assertFalse(flower['prefecture_level'])
        for original, updated in zip(items, result):
            for field in ('id', 'label', 'production_area', 'source_url', 'description', 'category'):
                self.assertEqual(original[field], updated[field])
            if explicitly_prefecture_wide(original['production_area'], original['prefecture']):
                self.assertEqual(original['lat'], updated['lat'])
                self.assertTrue(updated['prefecture_level'])
        self.assertEqual(items, json.loads((ROOT / 'data/official.json').read_text()))

    def test_duplicate_office_with_foreign_address_and_aliases(self):
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        by_label = {x['label']: x for x in apply_points(items, registry)}
        # P05-22 also lists 茨城町役場 at 土浦市; the address-consistent record wins.
        self.assertAlmostEqual(by_label['飯沼栗']['lat'], 36.286919122592984)
        self.assertEqual(by_label['ルイベ']['city'], '石狩市')
        # 巻柿 (宇城地域、上益城郡山都市) follows its first place, the named area 宇城地域.
        for label, city in [('いもべらあずき', 'いの町'), ('えびみそ汁', '三豊市'), ('巻柿', '宇城市')]:
            self.assertEqual(by_label[label]['city'], city)
            self.assertFalse(by_label[label]['prefecture_level'])

    def test_reject_alias_without_evidence(self):
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        item = next(x for x in items if x['label'] == 'いもべらあずき')
        for mutate in [lambda p: p.pop('alias_source_url'), lambda p: p.update(source_text='吾北村')]:
            bad = copy.deepcopy(registry)
            mutate(bad['points'][item['id']])
            with self.assertRaises(AssertionError):
                apply_points(items, bad)

    def test_first_place_decides_named_area(self):
        self.assertEqual(first_place('埼玉県秩父地域、本庄市', '埼玉県'), '秩父地域')
        self.assertEqual(first_place('日田・玖珠地方', '大分県'), '日田')
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        by_label = {x['label']: x for x in apply_points(items, registry)}
        # 秩父地域 precedes 本庄市, so the reviewed area wins over the later municipality.
        self.assertEqual((by_label['つみっこ']['city'], by_label['つみっこ']['coordinate_label']), ('秩父市', '秩父地域'))
        self.assertEqual(by_label['つみっこ']['coordinate_kind'], 'named_area_office')
        # Rejected area names keep their earlier result: 庄内町 is not the centre of 庄内地域.
        self.assertTrue(by_label['孟宗汁']['prefecture_level'])
        self.assertEqual(by_label['かます寿司']['city'], '久留米市')

    def test_reject_named_area_that_is_not_first(self):
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        item = next(x for x in items if x['label'] == 'つみっこ')
        for field, value in [('source_text', '本庄市'), ('municipality', '本庄市')]:
            bad = copy.deepcopy(registry)
            bad['points'][item['id']][field] = value
            with self.assertRaises(AssertionError):
                apply_points(items, bad)
        # A rejected area (日高地方 → 日高町) must not pass even as the first place.
        item = next(x for x in items if first_place(x['production_area'], x['prefecture']) == '日高地方'
                    and x['prefecture'] == '北海道')
        bad = copy.deepcopy(registry)
        bad['points'][item['id']] = dict(bad['points'][next(iter(bad['points']))], prefecture='北海道',
                                         municipality='日高町', office='日高町役場', kind='named_area_office',
                                         selection='first_place_in_source', source_text='日高地方')
        with self.assertRaises(AssertionError):
            apply_points(items, bad)

    def test_reject_points_outside_source_area_or_wrong_prefecture(self):
        items = json.loads((ROOT / 'data/official.json').read_text())
        registry = json.loads((ROOT / 'data/production_points.json').read_text())
        item = next(x for x in items if x['label'] == '豊橋花穂')
        for field, value in [('municipality', '名古屋市'), ('prefecture', '北海道')]:
            bad = copy.deepcopy(registry)
            bad['points'][item['id']][field] = value
            with self.assertRaises(AssertionError):
                apply_points(items, bad)


if __name__ == '__main__':
    unittest.main()
