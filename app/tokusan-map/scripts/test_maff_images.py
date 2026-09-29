import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from build_images import ROOT, approved_maff_photos
from build_maff_images import PERMISSION, LICENSE_URL, archive_photo, zip_candidates


class MaffImagesTest(unittest.TestCase):
    def item(self):
        return {'id': 'local-1234567890abcdef', 'label': '料理/別名', 'prefecture': '埼玉県',
                'source_kind': 'cuisine',
                'source_url': 'https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/search_menu/menu/test.html'}

    def html(self, permission=PERMISSION):
        # The first image is third-party material and must never be selected.
        return f'<h2>埼玉県</h2><h2>料理／別名（よみ）</h2><p>{permission}</p><img src="third-party.jpg"><p>画像提供元：第三者</p><div class="js_modal01"><div class="dl_img"><img alt="料理／別名" src="../../img/allowed.jpg"></div><a href="../../img/allowed.zip">著作権に同意してダウンロード</a></div>'

    def test_only_individually_permitted_matching_zip_photos(self):
        result = zip_candidates(self.html(), self.item())
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]['zip_url'].endswith('/img/allowed.zip'))
        self.assertNotIn('第三者', result[0]['credit'])
        for html in [self.html(''), self.html().replace('埼玉県', '宮崎県'),
                     self.html().replace('料理／別名', '別の料理'),
                     self.html().replace('../../img/allowed.zip', 'https://example.org/file.zip'),
                     self.html().replace('allowed.zip', 'allowed.jpg')]:
            self.assertEqual(zip_candidates(html, self.item()), [])

    def test_zip_original_is_retained_and_unsupported_files_rejected(self):
        content = b'\xff\xd8\xfforiginal-photo'
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as archive:
            archive.writestr('README.txt', 'not an image')
            archive.writestr('photos/original.jpg', content)
        member, actual, extension = archive_photo(blob.getvalue())
        self.assertEqual((member, actual, extension), ('photos/original.jpg', content, 'jpg'))
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as archive:
            archive.writestr('not-a-photo.jpg', '<svg></svg>')
        with self.assertRaises(ValueError):
            archive_photo(blob.getvalue())

    def test_registry_validates_identity_permission_paths_and_original_hash(self):
        item = self.item();content = b'\xff\xd8\xfforiginal-photo';digest = hashlib.sha256(content).hexdigest()
        url = '/photos/maff/' + item['id'] + '-' + digest[:16] + '.jpg'
        photo = {'url': url, 'original_url': url, 'license': 'PDL 1.0（ZIP配布写真）',
                 'license_url': LICENSE_URL, 'artist': '', 'credit': '出典：農林水産省',
                 'attribution': '', 'source_name': '農林水産省', 'source_url': item['source_url'],
                 'evidence_url': item['source_url'], 'file_name': 'original.jpg',
                 'match_method': 'maff_zip', 'checked_at': '2026-09-29', 'caption': '',
                 'label': item['label'], 'prefecture': item['prefecture'], 'permission': PERMISSION,
                 'zip_url': 'https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/img/allowed.zip',
                 'image_sha256': digest, 'page_sha256': 'a'*64, 'zip_sha256': 'b'*64}
        def manifest(entry):
            return {'photos': {item['id']: entry}}
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory);file = frontend / url.lstrip('/')
            file.parent.mkdir(parents=True);file.write_bytes(content)
            self.assertEqual(approved_maff_photos(manifest(photo), [item], frontend)[item['id']]['url'], url)
            for key, wrong in [('permission', ''), ('label', '別料理'), ('prefecture', '宮崎県'),
                               ('source_url', 'https://example.org'), ('license_url', ''),
                               ('url', '/photos/maff/../../other.jpg'), ('image_sha256', 'a'*64),
                               ('zip_url', 'https://example.org/img/allowed.zip')]:
                with self.subTest(field=key), self.assertRaises(ValueError):
                    approved_maff_photos(manifest(dict(photo, **{key: wrong})), [item], frontend)
            file.write_bytes(content + b'changed')
            with self.assertRaises(ValueError):
                approved_maff_photos(manifest(photo), [item], frontend)

    def test_published_maff_assets_and_source_integrity(self):
        manifest = json.loads((ROOT / 'data/maff_images.json').read_text())
        official = json.loads((ROOT / 'data/official.json').read_text())
        result = approved_maff_photos(manifest, official, ROOT / 'frontend')
        registered = json.loads((ROOT / 'data/images.json').read_text())['photos']
        self.assertTrue(result)
        for key, photo in result.items():
            self.assertEqual(registered[key], photo)
        public_files = {path.name for path in (ROOT / 'frontend/photos/maff').iterdir()}
        self.assertEqual(public_files, {Path(photo['url']).name for photo in result.values()})


if __name__ == '__main__':
    unittest.main()
