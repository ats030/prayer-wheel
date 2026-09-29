import json
import unittest
from pathlib import Path
from build_images import article_matches, candidate_rejection, licensed_photo, reviewed_candidates
from find_image_candidates import inspect_candidates

ROOT = Path(__file__).resolve().parent.parent


class ImagesTest(unittest.TestCase):
    def info(self, license='CC BY-SA 4.0', license_url='https://creativecommons.org/licenses/by-sa/4.0/'):
        return {'mime': 'image/jpeg', 'url': 'https://upload.wikimedia.org/example.jpg',
                'thumburl': 'https://thumb.wikimedia.org/example.jpg',
                'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Example.jpg',
                'extmetadata': {'License': {'value': 'cc-by-sa-4.0'},
                                'LicenseShortName': {'value': license},
                                'LicenseUrl': {'value': license_url},
                                'Artist': {'value': '<a href="/wiki/User:Example">Example author</a>'}}}

    def test_per_file_commercial_license_and_attribution(self):
        photo, reason = licensed_photo(self.info())
        self.assertEqual(reason, 'available')
        self.assertEqual(photo['artist'], 'Example author')
        self.assertEqual(photo['url'], 'https://thumb.wikimedia.org/example.jpg')
        for family in ['by-nc', 'by-nd', 'by-nc-sa']:
            self.assertEqual(licensed_photo(self.info(license_url=f'https://creativecommons.org/licenses/{family}/4.0/'))[1], 'unsupported_license')
        info = self.info(); info['extmetadata'].pop('Artist')
        self.assertEqual(licensed_photo(info)[1], 'missing_artist')
        info = self.info(); info['extmetadata']['Artist'] = []
        self.assertEqual(licensed_photo(info)[1], 'missing_artist')
        info = self.info(); info.pop('url')
        self.assertEqual(licensed_photo(info)[1], 'missing_image')
        info = self.info(); info['mime'] = 'image/svg+xml'
        self.assertEqual(licensed_photo(info)[1], 'not_a_photo')
        info = self.info(); info['descriptionurl'] = 'https://ja.wikipedia.org/wiki/File:Example.jpg'
        self.assertEqual(licensed_photo(info)[1], 'not_on_commons')
        info = self.info(); info['thumburl'] = 'https://example.org/example.jpg'
        self.assertEqual(licensed_photo(info)[1], 'missing_image')
        self.assertEqual(licensed_photo({'extmetadata': []})[1], 'missing_license')

    def test_cc0_and_public_domain_keep_distinct_terms(self):
        for code, label, path in [('cc0', 'CC0', 'zero'), ('pd', 'Public domain', 'mark')]:
            info = self.info(label, '')
            info['extmetadata']['License']['value'] = code
            info['extmetadata'].pop('Artist')
            photo, reason = licensed_photo(info)
            self.assertEqual(reason, 'available')
            self.assertEqual(photo['license_url'], f'https://creativecommons.org/publicdomain/{path}/1.0/')

    def test_generic_redirects_and_manufacturer_images_are_not_products(self):
        review = {'approved_article_aliases': {'いぶりがっこ': 'いぶり漬け'}}
        self.assertTrue(article_matches('いぶりがっこ', {'title': 'いぶり漬け'}, review))
        for name, redirected in [('大鰐温泉もやし', '大鰐温泉'), ('玉こんにゃく', 'コンニャク'), ('バッテラ', '寿司')]:
            self.assertFalse(article_matches(name, {'title': redirected}, review))
        self.assertFalse(article_matches('料理', {'title': '料理', 'pageprops': {'disambiguation': ''}}, review))
        self.assertEqual(candidate_rejection('Q1', 'Brand.jpg', 'wikidata_claim', {'Q1': ['菓子']},
            {'菓子': {'title': '菓子', 'pageprops': {'wikibase_item': 'Q2'}}}, review), 'article_entity_mismatch')

    def test_discovery_is_not_product_approval(self):
        # A valid commercial license on a search result proves no product match.
        choices = [{'file': 'Wrong.jpg', 'method': 'search', 'evidence': 'https://commons.wikimedia.org/wiki/File:Wrong.jpg'}]
        candidates = inspect_candidates(choices + choices, {'Wrong.jpg': self.info()}, {})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(reviewed_candidates({'candidates': candidates}, {'Q1'}), {})
        self.assertEqual(inspect_candidates(choices, {'Wrong.jpg': self.info()},
                                           {'excluded_files': {'Wrong.jpg': 'wrong dish'}}), [])
        self.assertEqual(inspect_candidates(choices, {'Wrong.jpg': self.info(license_url='')}, {}), [])

    def test_review_requires_identity_evidence_and_nonexcluded_file(self):
        entry = {'file_name': 'Product.jpg', 'evidence_url': 'https://commons.wikimedia.org/wiki/File:Product.jpg',
                 'reason': 'Label and actual product checked', 'caption': ''}
        review = {'approved_photos': {'Q1': entry}}
        self.assertEqual(reviewed_candidates(review, {'Q1'})['Q1'][0][1], 'reviewed_product')
        with self.assertRaises(ValueError):
            reviewed_candidates(review, {'Q2'})
        for field in ['file_name', 'evidence_url', 'reason']:
            with self.subTest(field=field), self.assertRaises(ValueError):
                reviewed_candidates({'approved_photos': {'Q1': dict(entry, **{field: ''})}}, {'Q1'})
        with self.assertRaises(ValueError):
            reviewed_candidates(dict(review, excluded_files={'Product.jpg': 'wrong dish'}), {'Q1'})
        blocked = dict(review, excluded_items={'Q1': 'regional mismatch'})
        self.assertEqual(candidate_rejection('Q1', 'Old.jpg', 'exact_article', {}, {}, blocked), 'unconfirmed_product_variant')
        self.assertEqual(candidate_rejection('Q1', 'Product.jpg', 'reviewed_product', {}, {}, blocked), '')
        self.assertEqual(candidate_rejection('Q1', 'Bad.jpg', 'reviewed_product', {}, {},
                         dict(blocked, excluded_files={'Bad.jpg': 'wrong dish'})), 'unrelated_photo')

    def test_published_registry_and_known_misidentifications(self):
        data = json.loads((ROOT / 'data/images.json').read_text())
        public = json.loads((ROOT / 'frontend/images.json').read_text())
        curated = json.loads((ROOT / 'data/curation.json').read_text())['include']
        official = json.loads((ROOT / 'data/official.json').read_text())
        catalog_ids = set(curated) | {entry['id'] for entry in official}
        self.assertEqual(set(data['audit']), catalog_ids)
        self.assertEqual(len(catalog_ids), 651)
        self.assertEqual(public, {key: data[key] for key in ['version', 'photos', 'blocked_fallback']})
        self.assertEqual(data['stats']['registered'], len(data['photos']))
        self.assertEqual(sum(data['stats']['reasons'].values()), len(catalog_ids))
        review = json.loads((ROOT / 'data/image_review.json').read_text())
        for item_id, photo in data['photos'].items():
            self.assertIn(item_id, catalog_ids)
            self.assertTrue(photo['license_url'] and photo['source_url'] and photo['evidence_url'])
            self.assertNotIn(photo['file_name'].replace('_', ' '), review['excluded_files'])
            if '/licenses/' in photo['license_url']:
                self.assertTrue(photo['artist'])
        for item_id in ['local-0e4354f5f59adace', 'local-e4b1b086bfc4f7f0',
                        'Q136396484']:
            self.assertNotIn(item_id, data['photos'])
        for item_id in ['local-3784823d3f2b152f', 'local-cfc537e0cedc6558']:
            self.assertEqual(data['photos'][item_id]['match_method'], 'maff_zip')
            self.assertEqual(data['photos'][item_id]['source_name'], '農林水産省')
        self.assertEqual(data['photos']['local-b197b0701967b125']['file_name'], '八幡号 1938.jpg')
        self.assertEqual(data['photos']['local-be8abc00071acee2']['file_name'], 'Takana meshi set by woinary in Aso, Kumamoto.jpg')
        self.assertIn('Q11258608', data['blocked_fallback'])
        self.assertIn('Q136396484', data['blocked_fallback'])
        self.assertEqual(data['audit']['Q136396484'], 'unconfirmed_product_variant')
        self.assertEqual(data['photos']['Q17192072']['file_name'], 'アリランラーメン.jpg')
        self.assertEqual(data['photos']['Q6368803']['file_name'], 'Aichi_Prefectural_Ceramic_Museum_(38).jpg')
        self.assertIn('local-3f1a02a8d3cb5416', data['photos'])  # official Yubari melon


if __name__ == '__main__':
    unittest.main()
