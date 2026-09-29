import unittest
from classify_regions import classify, load_regions


class RegionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definitions = {p['prefecture']: p for p in load_regions()}

    def labels(self, area, prefecture):
        definition = self.definitions[prefecture]
        ids, scope, _ = classify(area, prefecture, definition)
        return [r['label'] for r in definition['regions'] if r['id'] in ids], scope

    def test_broad_regions_and_multiple_membership(self):
        self.assertEqual(self.labels('北海道夕張市', '北海道'), (['道央'], 'regional'))
        self.assertEqual(self.labels('北海道上川郡清水町', '北海道'), (['道東'], 'regional'))
        self.assertEqual(self.labels('下北地方、津軽地方', '青森県'), (['津軽', '下北'], 'regional'))
        self.assertEqual(self.labels('愛知県豊橋市、豊川市、新城市', '愛知県'), (['東三河', '奥三河'], 'regional'))

    def test_whole_prefecture_requires_explicit_evidence(self):
        for area in ['宮城県', '宮城県内', '県内', '']:
            self.assertEqual(self.labels(area, '宮城県'), ([], 'unknown'))
        self.assertEqual(self.labels('県内全域（白石市）', '宮城県'), ([], 'prefecture'))
        self.assertEqual(self.labels('会津地方全域', '福島県'), (['会津'], 'regional'))
        self.assertEqual(self.labels('沿岸中心に県内全域', '秋田県'), ([], 'prefecture'))

    def test_embedded_names_do_not_add_an_unrelated_region(self):
        cases = [('熊野町、安芸高田市', '広島県', ['広島市周辺', '芸北']),
                 ('大阪府東大阪市', '大阪府', ['河内']),
                 ('愛知県北名古屋市', '愛知県', ['尾張西部']),
                 ('岡山県吉備中央町', '岡山県', ['備前']),
                 ('栃木県那須烏山市、那珂川町', '栃木県', ['県央']),
                 ('高知県須崎市、梼原町', '高知県', ['西部']),
                 ('神奈川県小田原市', '神奈川県', ['箱根'])]
        for area, pref, expected in cases:
            self.assertEqual(self.labels(area, pref), (expected, 'regional'))
        self.assertEqual(self.labels('東峰村', '福岡県'), (['福岡'], 'regional'))

    def test_parent_area_explanation_does_not_expand_city_scope(self):
        self.assertEqual(self.labels('長岡市（中越地方）', '新潟県'), (['長岡・柏崎'], 'regional'))
        self.assertEqual(self.labels('中越地方', '新潟県'),
                         (['弥彦・燕三条', '長岡・柏崎', '湯沢・魚沼'], 'regional'))
        self.assertEqual(self.labels('県央地域（盛岡市、花巻市、紫波町、遠野市など）', '岩手県'),
                         (['県央', '県南'], 'regional'))

    def test_compatibility_names_and_unicode(self):
        self.assertEqual(self.labels('島根県⼤⽥市三瓶町', '島根県'), (['石見'], 'regional'))
        self.assertEqual(self.labels('伊勢志摩食文化圏、北勢食文化圏、東紀州食文化圏', '三重県'),
                         (['北勢', '伊勢志摩', '東紀州'], 'regional'))
        self.assertEqual(self.labels('小浜市新保区', '福井県'), (['若狭路'], 'regional'))


if __name__ == '__main__':
    unittest.main()
