#!/usr/bin/env python3
"""Import only explicitly reusable ZIP photos from exact MAFF recipe pages.

Non-downloadable photographs, including third-party-provided pictures on the
same pages, never qualify. Original archive images are stored without edits.
"""
import argparse
import hashlib
import io
import json
import re
import time
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from build_images import ROOT, USER_AGENT

PERMISSION = 'ZIPファイルをダウンロードできる画像は許可なく使用することができます。'
LICENSE_URL = 'https://www.digital.go.jp/resources/open_data/public_data_license_v1.0'
MAX_BYTES = 12 * 1024 * 1024


def normalized(value):
    return re.sub(r'[\s／/（）()]+', '', value)


def zip_candidates(html, item):
    soup = BeautifulSoup(html, 'html.parser')
    headings = [heading.get_text(' ', strip=True) for heading in soup.find_all('h2')]
    text = soup.get_text(' ', strip=True)
    if (PERMISSION not in text or item['prefecture'] not in headings
            or not any(normalized(item['label']) in normalized(heading) for heading in headings)):
        return []
    result = []
    for box in soup.select('div.js_modal01'):
        image = box.select_one('.dl_img img')
        if not image or normalized(image.get('alt', '')) != normalized(item['label']):
            continue
        for link in box.select('a[href]'):
            url = urljoin(item['source_url'], link['href'])
            parsed = urlparse(url)
            if (parsed.scheme == 'https' and parsed.hostname == 'www.maff.go.jp'
                    and parsed.path.startswith('/j/keikaku/syokubunka/k_ryouri/img/')
                    and parsed.path.endswith('.zip') and '著作権' in link.get_text()):
                result.append({'zip_url': url, 'alt': image['alt'],
                               'credit': box.get_text(' ', strip=True).split('「リンクについて')[0].strip()})
    return result


def archive_photo(blob):
    if len(blob) > MAX_BYTES:
        raise ValueError('Oversized photo ZIP')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for member in archive.infolist():
            if member.is_dir() or member.filename.startswith('__MACOSX/'):
                continue
            if not re.search(r'\.(?:jpe?g|png)$', member.filename, re.I):
                continue
            if member.file_size > MAX_BYTES:
                raise ValueError('Oversized archive image')
            content = archive.read(member)
            if content.startswith(b'\xff\xd8\xff'):
                return member.filename, content, 'jpg'
            if content.startswith(b'\x89PNG\r\n\x1a\n'):
                return member.filename, content, 'png'
    raise ValueError('ZIP has no supported image')


def fetch_cached(session, url, cache, extension):
    file = cache / (hashlib.sha256(url.encode()).hexdigest() + extension)
    if file.exists():
        return file.read_bytes()
    for attempt in range(3):
        time.sleep(.4 if not attempt else 2 ** attempt)
        response = session.get(url, timeout=30)
        if response.status_code in (429, 503):
            continue
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError('Oversized source download')
        file.write_bytes(response.content)
        return response.content
    raise RuntimeError('Source unavailable: ' + url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/tokusan-maff-photo-cache'))
    parser.add_argument('--checked-at', default=date.today().isoformat(), help='ISO date of the rights/content audit')
    args = parser.parse_args()
    date.fromisoformat(args.checked_at)
    args.cache.mkdir(parents=True, exist_ok=True)
    destination = ROOT / 'frontend/photos/maff'
    destination.mkdir(parents=True, exist_ok=True)
    registry = json.loads((ROOT / 'data/images.json').read_text())
    manifest_path = ROOT / 'data/maff_images.json'
    old = json.loads(manifest_path.read_text()).get('photos', {}) if manifest_path.exists() else {}
    items = [item for item in json.loads((ROOT / 'data/official.json').read_text())
             if item['source_kind'] == 'cuisine' and (item['id'] not in registry['photos'] or item['id'] in old)]
    session = requests.Session()
    session.headers['User-Agent'] = USER_AGENT
    photos = {}
    for index, item in enumerate(items, 1):
        page = fetch_cached(session, item['source_url'], args.cache, '.html')
        choices = zip_candidates(page, item)
        if choices:
            chosen = choices[0]
            blob = fetch_cached(session, chosen['zip_url'], args.cache, '.zip')
            member, content, extension = archive_photo(blob)
            digest = hashlib.sha256(content).hexdigest()
            filename = item['id'] + '-' + digest[:16] + '.' + extension
            (destination / filename).write_bytes(content)
            local_url = '/photos/maff/' + filename
            photos[item['id']] = {'url': local_url, 'original_url': local_url,
                'license': 'PDL 1.0（ZIP配布写真）', 'license_url': LICENSE_URL,
                'artist': '', 'credit': '出典：農林水産省「うちの郷土料理」',
                'attribution': chosen['credit'], 'source_name': '農林水産省',
                'source_url': item['source_url'], 'evidence_url': item['source_url'],
                'file_name': member, 'match_method': 'maff_zip', 'checked_at': args.checked_at,
                'caption': '', 'label': item['label'], 'prefecture': item['prefecture'],
                'permission': PERMISSION, 'zip_url': chosen['zip_url'],
                'page_sha256': hashlib.sha256(page).hexdigest(),
                'zip_sha256': hashlib.sha256(blob).hexdigest(), 'image_sha256': digest}
        if index % 10 == 0:
            print(f'Checked {index}/{len(items)} recipe pages; permitted ZIP photos {len(photos)}', flush=True)
    manifest_path.write_text(json.dumps({'checked_at': args.checked_at, 'photos': photos}, ensure_ascii=False, indent=2) + '\n')
    print(f'Imported {len(photos)} unchanged, explicitly permitted ZIP photographs', flush=True)


if __name__ == '__main__':
    main()
