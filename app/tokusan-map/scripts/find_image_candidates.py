#!/usr/bin/env python3
"""Discover licensed photo candidates for missing products; never publish results.

Article images, product categories, and optional exact-label Commons searches
include unrelated illustrations and buildings. Every selection needs an explicit
approved_photos entry in image_review.json before build_images.py can publish it.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

from build_images import API, ROOT, article_matches, batches, claim, licensed_photo, plain


def candidate(filename, evidence, method):
    return {'file': filename.removeprefix('File:').removeprefix('ファイル:'),
            'evidence': evidence, 'method': method}


def inspect_candidates(choices, infos, review):
    result, seen = [], set()
    for choice in choices:
        name = choice['file'].replace('_', ' ')
        if name in seen or name in review.get('excluded_files', {}):
            continue
        seen.add(name)
        info = infos.get(name, {})
        photo, _ = licensed_photo(info)
        if not photo:
            continue
        metadata = info.get('extmetadata', {})
        def value(key):
            field = metadata.get(key, {})
            return plain(field.get('value', '')) if isinstance(field, dict) else ''
        result.append(dict(choice, description=value('ImageDescription'),
                           categories=value('Categories'), photo=photo))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/tokusan-photo-candidates-cache'))
    parser.add_argument('--output', type=Path, default=Path('/tmp/tokusan-photo-candidates.json'))
    parser.add_argument('--search', action='store_true', help='Also search Commons for exact product labels')
    args = parser.parse_args()
    registry = json.loads((ROOT / 'data/images.json').read_text())
    review = json.loads((ROOT / 'data/image_review.json').read_text())
    curated = json.loads((ROOT / 'data/curation.json').read_text())['include']
    official = json.loads((ROOT / 'data/official.json').read_text())
    items = {key: {'label': entry['wiki_title'], 'titles': [entry['wiki_title']]}
             for key, entry in curated.items() if key not in registry['photos']}
    items.update({entry['id']: {'label': entry['label'], 'titles': re.split('[／/]', entry['label'])}
                  for entry in official if entry['id'] not in registry['photos']})
    api, pages, entities, infos = API(args.cache), {}, {}, {}
    for batch in batches((title for item in items.values() for title in item['titles']), 20):
        data = api.query('ja.wikipedia.org', action='query', titles='|'.join(batch),
                         prop='images|pageprops', imlimit=500, redirects=1).get('query', {})
        by_title = {page['title']: page for page in data.get('pages', {}).values()}
        redirects = {entry['from']: entry['to'] for entry in data.get('normalized', []) + data.get('redirects', [])}
        for title in batch:
            resolved, seen = title, set()
            while resolved in redirects and resolved not in seen:
                seen.add(resolved)
                resolved = redirects[resolved]
            pages[title] = by_title.get(resolved, {})
        print(f'Articles checked: {len(pages)}', flush=True)
    for batch in batches(key for key in items if key.startswith('Q')):
        entities.update(api.query('www.wikidata.org', action='wbgetentities', ids='|'.join(batch),
                                  props='claims|labels|sitelinks', languages='en|ja').get('entities', {}))
    choices = {}
    for key, item in items.items():
        choices[key] = []
        for title in item['titles']:
            page = pages.get(title, {})
            if article_matches(title, page, review):
                evidence = 'https://ja.wikipedia.org/wiki/' + quote(page['title'])
                choices[key].extend(candidate(image['title'], evidence, 'article') for image in page.get('images', []))
        entity = entities.get(key, {})
        category = claim(entity, 'P373')
        if not category:
            category = entity.get('sitelinks', {}).get('commonswiki', {}).get('title', '').removeprefix('Category:')
            if not entity.get('sitelinks', {}).get('commonswiki', {}).get('title', '').startswith('Category:'):
                category = ''
        if category:
            data = api.query('commons.wikimedia.org', action='query', list='categorymembers',
                             cmtitle='Category:' + category, cmtype='file', cmlimit=100)
            evidence = 'https://commons.wikimedia.org/wiki/Category:' + quote(category)
            choices[key].extend(candidate(image['title'], evidence, 'category')
                                for image in data.get('query', {}).get('categorymembers', []))
    for batch in batches(choice['file'] for group in choices.values() for choice in group
                         if re.search(r'\.(?:jpe?g|png|webp)$', choice['file'], re.I)):
        data = api.query('commons.wikimedia.org', action='query', titles='|'.join('File:' + name for name in batch),
                         prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=800)
        for page in data.get('query', {}).get('pages', {}).values():
            infos[page['title'].removeprefix('File:').replace('_', ' ')] = (page.get('imageinfo') or [{}])[0]
    result = {}
    for index, (key, item) in enumerate(items.items(), 1):
        if args.search:
            english = entities.get(key, {}).get('labels', {}).get('en', {}).get('value', '')
            search_titles = item['titles'] + ([english] if english else [])
            for title in dict.fromkeys(search_titles):
                data = api.query('commons.wikimedia.org', action='query', generator='search',
                                 gsrsearch='"' + title.replace('"', '') + '"', gsrnamespace=6, gsrlimit=5,
                                 prop='imageinfo', iiprop='url|extmetadata|mime', iiurlwidth=800)
                for page in data.get('query', {}).get('pages', {}).values():
                    info = (page.get('imageinfo') or [{}])[0]
                    name = page['title'].removeprefix('File:')
                    infos[name.replace('_', ' ')] = info
                    choices[key].append(candidate(name, info.get('descriptionurl', ''), 'search'))
        candidates = inspect_candidates(choices[key], infos, review)
        if candidates:
            result[key] = {'label': item['label'], 'candidates': candidates}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        if index % 10 == 0:
            print(f'Checked {index}/{len(items)} products; candidates for {len(result)}', flush=True)
    print(f'Candidate report: {args.output}; not approved for publication', flush=True)


if __name__ == '__main__':
    main()
