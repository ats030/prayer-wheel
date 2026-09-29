#!/usr/bin/env python3
"""Audit photo coverage and publish verified Commons images for catalog IDs.

Candidates come from Wikidata claims, exact Wikipedia titles, and reviewed files.
Search results are never published without an explicit per-product review.
API responses are cached outside the repository for reproducible audits.
"""
import argparse
import collections
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = 'TokusanMap/1.0 (https://tokusan-map-736831430371.asia-northeast1.run.app/; catalog photo audit)'
ALLOWED_MIME = {'image/jpeg', 'image/png', 'image/webp'}
MAFF_ZIP_PERMISSIONS = (
    'ZIPファイルをダウンロードできる画像は許可なく使用することができます。',
    '※ダウンロード可能な画像を使用する場合は「リンク・著作権について」をご一読の上、出典を農林水産省「うちの郷土料理」と明記し、ご利用ください。なお、画像提供元の記載がある場合は画像提供元も併せてご記載ください。',
)


def plain(value):
    if '<' not in (value or ''):
        return value or ''
    return BeautifulSoup(value or '', 'html.parser').get_text(' ', strip=True)


def licensed_photo(info):
    metadata = info.get('extmetadata', {})
    if not isinstance(metadata, dict):
        return None, 'missing_license'
    def value(key):
        field = metadata.get(key, {})
        return plain(field.get('value', '')) if isinstance(field, dict) else ''
    license_url = value('LicenseUrl')
    url = urlparse(license_url)
    license_name = value('LicenseShortName') or value('License')
    cc = url.hostname == 'creativecommons.org' and bool(re.fullmatch(
        r'/licenses/by(?:-sa)?/(?:(?:1\.0|2\.0|2\.5|3\.0|4\.0)/?|2\.1/jp/(?:deed\.(?:en|ja))?)', url.path))
    public_domain = value('License') in {'pd', 'cc-zero', 'cc0'} and license_name in {'Public domain', 'CC0', 'CC0 1.0'}
    if not cc and not public_domain:
        return None, 'unsupported_license'
    if info.get('mime') not in ALLOWED_MIME:
        return None, 'not_a_photo'
    artist = value('Artist')
    if cc and not artist:
        return None, 'missing_artist'
    original_url = info.get('url', '')
    image_url = info.get('thumburl') or original_url
    allowed_hosts = {'upload.wikimedia.org', 'thumb.wikimedia.org'}
    if any(urlparse(candidate).hostname not in allowed_hosts for candidate in (image_url, original_url)):
        return None, 'missing_image'
    source_url = info.get('descriptionurl', '')
    if urlparse(source_url).hostname != 'commons.wikimedia.org':
        return None, 'not_on_commons'
    if not license_url and public_domain:
        kind = 'zero' if value('License') in {'cc-zero', 'cc0'} else 'mark'
        license_url = f'https://creativecommons.org/publicdomain/{kind}/1.0/'
    return {'url': image_url, 'original_url': original_url, 'license': license_name,
            'license_url': license_url, 'artist': artist, 'credit': value('Credit'),
            'attribution': value('Attribution'), 'source_url': source_url}, 'available'


class API:
    def __init__(self, cache):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers['User-Agent'] = USER_AGENT

    def query(self, host, **params):
        params.update(format='json', maxlag=5)
        key = hashlib.sha256(json.dumps([host, params], sort_keys=True).encode()).hexdigest()
        path = self.cache / (key + '.json')
        if path.exists():
            return json.loads(path.read_text())
        for attempt in range(3):
            time.sleep(.3 if attempt == 0 else 2 ** attempt)
            response = self.session.get('https://' + host + '/w/api.php', params=params, timeout=40)
            if response.status_code in (429, 503):
                time.sleep(min(float(response.headers.get('Retry-After', 2)), 30))
                continue
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                if data['error'].get('code') == 'maxlag':
                    continue
                raise RuntimeError(data['error'])
            path.write_text(json.dumps(data, ensure_ascii=False))
            return data
        raise RuntimeError(f'API unavailable: {host}')


def batches(values, size=50):
    values = list(dict.fromkeys(values))
    for index in range(0, len(values), size):
        yield values[index:index + size]


def claim(entity, key):
    for statement in entity.get('claims', {}).get(key, []):
        value = statement.get('mainsnak', {}).get('datavalue', {}).get('value')
        if isinstance(value, str):
            return value
    return ''


def article_matches(title, page, review):
    """A redirect is not evidence that a generic article depicts this product."""
    expected = review.get('approved_article_aliases', {}).get(title, title)
    return (page.get('title', '').replace('_', ' ') == expected.replace('_', ' ')
            and 'missing' not in page
            and 'disambiguation' not in page.get('pageprops', {}))


def candidate_rejection(item_id, filename, method, titles, pages, review):
    if item_id in review.get('excluded_items', {}) and method != 'reviewed_product':
        return 'unconfirmed_product_variant'
    if filename.replace('_', ' ') in review.get('excluded_files', {}):
        return 'unrelated_photo'
    if method == 'wikidata_claim':
        article_entities = {pages.get(t, {}).get('pageprops', {}).get('wikibase_item')
                            for t in titles[item_id] if article_matches(t, pages.get(t, {}), review)} - {None}
        if article_entities and item_id not in article_entities:
            return 'article_entity_mismatch'
    return ''


def reviewed_candidates(review, catalog_ids):
    """Only explicit, evidenced approvals can promote discovered candidate files."""
    result = {}
    for item_id, entry in review.get('approved_photos', {}).items():
        if item_id not in catalog_ids:
            raise ValueError(f'Unknown catalog ID in photo review: {item_id}')
        filename = entry.get('file_name', '')
        evidence = entry.get('evidence_url', '')
        url = urlparse(evidence)
        if (not filename or not entry.get('reason', '').strip()
                or url.scheme != 'https'
                or url.hostname not in {'commons.wikimedia.org', 'ja.wikipedia.org'}
                or not url.path.startswith('/wiki/')):
            raise ValueError(f'Incomplete product photo review: {item_id}')
        if filename.replace('_', ' ') in review.get('excluded_files', {}):
            raise ValueError(f'Excluded file cannot be approved: {item_id}')
        result[item_id] = [(filename, 'reviewed_product', evidence)]
    return result


def category_file(api, category):
    data = api.query('commons.wikimedia.org', action='query', list='categorymembers',
                     cmtitle='Category:' + category, cmtype='file', cmlimit=100)
    words = [w for w in re.findall(r'[^\W_]+', category.lower()) if len(w.encode()) >= 3]
    best, score = '', 0
    for member in data.get('query', {}).get('categorymembers', []):
        name = member['title'].removeprefix('File:')
        if not re.search(r'\.(?:jpe?g|png|svg|webp|gif)$', name, re.I):
            continue
        got = sum(w in name.lower() for w in words)
        if got > score:
            best, score = name, got
    return best



def approved_maff_photos(manifest, official, frontend):
    """Validate the individually permitted, unchanged local ZIP-photo records."""
    catalog = {item['id']: item for item in official}
    result = {}
    for item_id, photo in manifest.get('photos', {}).items():
        item = catalog.get(item_id, {})
        zip_url = urlparse(photo.get('zip_url', ''))
        relative = photo.get('url', '')
        digest = photo.get('image_sha256', '')
        if (item.get('source_kind') != 'cuisine'
                or photo.get('source_url') != item.get('source_url')
                or photo.get('evidence_url') != item.get('source_url')
                or photo.get('label') != item.get('label')
                or photo.get('prefecture') != item.get('prefecture')
                or photo.get('permission') not in MAFF_ZIP_PERMISSIONS
                or photo.get('license_url') != 'https://www.digital.go.jp/resources/open_data/public_data_license_v1.0'
                or photo.get('source_name') != '農林水産省'
                or photo.get('license') != 'PDL 1.0（ZIP配布写真）'
                or photo.get('match_method') != 'maff_zip'
                or not photo.get('credit') or not photo.get('checked_at')
                or zip_url.scheme != 'https' or zip_url.hostname != 'www.maff.go.jp'
                or not zip_url.path.startswith('/j/keikaku/syokubunka/k_ryouri/img/')
                or not zip_url.path.endswith('.zip')
                or not re.fullmatch(r'/photos/maff/' + re.escape(item_id) + r'-[a-f0-9]{16}\.(?:jpg|png)', relative)
                or photo.get('original_url') != relative
                or any(not re.fullmatch('[a-f0-9]{64}', photo.get(field, ''))
                       for field in ['image_sha256', 'page_sha256', 'zip_sha256'])
                or digest[:16] not in relative):
            raise ValueError(f'Invalid individual MAFF photo permission: {item_id}')
        content = (frontend / relative.lstrip('/')).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f'MAFF photo content changed: {item_id}')
        if not (content.startswith(b'\xff\xd8\xff') or content.startswith(b'\x89PNG\r\n\x1a\n')):
            raise ValueError(f'MAFF file is not a supported image: {item_id}')
        result[item_id] = {key: photo[key] for key in [
            'url', 'original_url', 'license', 'license_url', 'artist', 'credit', 'attribution',
            'source_name', 'source_url', 'evidence_url', 'file_name', 'match_method', 'checked_at', 'caption']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/tokusan-photo-cache'))
    args = parser.parse_args()
    api = API(args.cache)
    review = json.loads((ROOT / 'data/image_review.json').read_text())
    curated = json.loads((ROOT / 'data/curation.json').read_text())['include']
    official = json.loads((ROOT / 'data/official.json').read_text())
    titles = {qid: [entry['wiki_title']] for qid, entry in curated.items()}
    titles.update({entry['id']: re.split('[／/]', entry['label']) for entry in official})
    pages = {}
    for batch in batches(t for values in titles.values() for t in values):
        data = api.query('ja.wikipedia.org', action='query', titles='|'.join(batch),
                         prop='pageimages|pageprops', piprop='name', redirects=1)
        result = data.get('query', {})
        by_title = {page['title']: page for page in result.get('pages', {}).values()}
        aliases = {r['from']: r['to'] for r in result.get('normalized', []) + result.get('redirects', [])}
        for title in batch:
            resolved, seen = title, set()
            while resolved in aliases and resolved not in seen:
                seen.add(resolved)
                resolved = aliases[resolved]
            pages[title] = by_title.get(resolved, {})
        print(f'Wikipedia titles checked: {len(pages)}', flush=True)
    entities = {}
    for batch in batches(curated):
        entities.update(api.query('www.wikidata.org', action='wbgetentities', ids='|'.join(batch), props='claims').get('entities', {}))
    existing_files = {}
    for qid, entity in entities.items():
        filename = claim(entity, 'P18')
        if not filename and (category := claim(entity, 'P373')):
            filename = category_file(api, category)
        existing_files[qid] = filename
    candidates = {}
    for item_id, article_titles in titles.items():
        choices = []
        if existing_files.get(item_id):
            choices.append((existing_files[item_id], 'wikidata_claim', 'https://www.wikidata.org/wiki/' + item_id))
        for title in article_titles:
            page = pages.get(title, {})
            if 'missing' in page or 'disambiguation' in page.get('pageprops', {}):
                continue
            filename = page.get('pageimage', '')
            if filename:
                choices.append((filename, 'exact_article', 'https://ja.wikipedia.org/wiki/' + quote(page['title'].replace(' ', '_'))))
        candidates[item_id] = choices
    approved = reviewed_candidates(review, titles)
    original_names = [name for choices in candidates.values() for name, _, _ in choices]
    for item_id, choices in approved.items():
        candidates[item_id] = choices + candidates[item_id]
    infos = {}
    # Keep the original batches reproducible; inspect reviewed additions separately.
    file_batches = list(batches(original_names)) + list(batches(
        name for choices in approved.values() for name, _, _ in choices if name not in original_names))
    for batch in file_batches:
        data = api.query('commons.wikimedia.org', action='query', titles='|'.join('File:' + name for name in batch),
                         prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=800)
        for page in data.get('query', {}).get('pages', {}).values():
            infos[page['title'].removeprefix('File:').replace('_', ' ')] = (page.get('imageinfo') or [{}])[0]
        print(f'Commons files checked: {len(infos)}', flush=True)
    baseline = sum(bool((info := infos.get(name.replace('_', ' '), {})).get('thumburl') or info.get('url')) and
                   bool(plain((info.get('extmetadata') or {}).get('License', {}).get('value', '')))
                   for name in existing_files.values() if name)
    photos, audit = {}, {}
    # A denied product must not reach the legacy resolver even with no current claims.
    blocked_fallback = [key for key in review.get('excluded_items', {})
                        if key.startswith('Q') and key in titles]
    for item_id, choices in candidates.items():
        reason = 'unconfirmed_product_variant' if item_id in review.get('excluded_items', {}) else 'no_exact_article_photo'
        old_file = existing_files.get(item_id)
        if old_file:
            rejected = candidate_rejection(item_id, old_file, 'wikidata_claim', titles, pages, review)
            old_photo, _ = licensed_photo(infos.get(old_file.replace('_', ' '), {}))
            if (rejected or not old_photo) and item_id not in blocked_fallback:
                blocked_fallback.append(item_id)
        # The curated product article is more specific than a manufacturer's P18.
        for filename, method, evidence in sorted(choices, key=lambda c: {'reviewed_product': 0, 'exact_article': 1}.get(c[1], 2)):
            rejected = candidate_rejection(item_id, filename, method, titles, pages, review)
            if method == 'exact_article' and not any(
                    article_matches(t, pages.get(t, {}), review)
                    and pages[t].get('pageimage') == filename for t in titles[item_id]):
                rejected = 'generic_article_redirect'
            if rejected:
                reason = rejected
                continue
            photo, reason = licensed_photo(infos.get(filename.replace('_', ' '), infos.get(filename, {})))
            if photo:
                photos[item_id] = dict(photo, file_name=filename, match_method=method,
                                       evidence_url=evidence, checked_at=review['reviewed_at'],
                                       caption=review.get('approved_photos', {}).get(item_id, {}).get('caption', '')
                                       if method == 'reviewed_product' else review.get('captions', {}).get(item_id, ''))
                break
        audit[item_id] = 'available' if item_id in photos else reason
        if item_id.startswith('Q') and choices and item_id not in photos and item_id not in blocked_fallback:
            blocked_fallback.append(item_id)
    maff_path = ROOT / 'data/maff_images.json'
    maff = approved_maff_photos(json.loads(maff_path.read_text()), official, ROOT / 'frontend') if maff_path.exists() else {}
    for item_id, photo in maff.items():
        if item_id not in photos:
            photos[item_id] = photo
            audit[item_id] = 'available'
    stats = {'total': len(titles), 'old_resolvable': baseline, 'registered': len(photos),
             'registered_official': sum(key.startswith('local-') for key in photos),
             'registered_maff': sum(photo.get('match_method') == 'maff_zip' for photo in photos.values()),
             'reasons': dict(collections.Counter(audit.values()))}
    output = {'version': review['reviewed_at'].replace('-', ''), 'stats': stats, 'photos': photos, 'audit': audit,
              'blocked_fallback': blocked_fallback}
    (ROOT / 'data/images.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'frontend/images.json').write_text(json.dumps({key: output[key] for key in
        ('version', 'photos', 'blocked_fallback')}, ensure_ascii=False) + '\n')
    print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
