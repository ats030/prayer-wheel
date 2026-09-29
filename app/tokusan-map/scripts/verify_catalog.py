#!/usr/bin/env python3
"""Verify the published catalog and, optionally, its official source pages."""
import argparse
import collections
import hashlib
import html
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

import requests
from import_production_points import apply_points
from classify_regions import classify, load_regions

ROOT = Path(__file__).resolve().parent.parent


def normalize(value):
    value = unicodedata.normalize('NFKC', html.unescape(re.sub('<[^>]*>', '', value)))
    return re.sub(r'\s+', '', value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-sources', action='store_true')
    parser.add_argument('--source-cache', type=Path, help='Optional HTML snapshot cache')
    args = parser.parse_args()
    official = json.loads((ROOT / 'data/official.json').read_text())
    official = apply_points(official, json.loads((ROOT / 'data/production_points.json').read_text()))
    curation = json.loads((ROOT / 'data/curation.json').read_text())
    con = sqlite3.connect(f'file:{ROOT / "frontend/tokusan.db"}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = {r['qid']: dict(r) for r in con.execute('SELECT * FROM tokusan')}
    assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    con.close()
    assert len(rows) == len(curation['include']) + len(official)
    assert len(rows) >= 500, f'Only {len(rows)} items'
    counts = collections.Counter(r['prefecture'] for r in rows.values())
    assert len(counts) == 47 and min(counts.values()) >= 5, counts
    assert len({r['id'] for r in official}) == len(official), 'Duplicate IDs'
    assert len({r['label'] for r in official}) == len(official), 'Duplicate names'
    definitions = {p['prefecture']: p for p in load_regions()}
    public = json.loads((ROOT / 'frontend/regions.json').read_text())
    expected = [dict(pref, regions=[{'id': r['id'], 'label': r['label']} for r in pref['regions']])
                for pref in definitions.values()]
    assert public == expected, 'Published region definitions differ from canonical data'
    for row in rows.values():
        ids, scope, basis = classify(row['production_area'] or row['city'] or row['place'],
                                     row['prefecture'], definitions[row['prefecture']])
        assert json.loads(row['region_ids']) == ids and row['region_scope'] == scope
        assert row['region_basis'] == basis and len(ids) == len(set(ids))
    for e in official:
        row = rows[e['id']]
        for target, source in [('label_ja', 'label'), ('source_url', 'source_url'),
                               ('source_name', 'source_name'), ('description', 'description'),
                               ('category', 'category'), ('production_area', 'production_area'),
                               ('prefecture', 'prefecture'), ('lat', 'lat'), ('lng', 'lng')]:
            assert row[target] == e[source], (e['id'], target)
        assert row['prefecture_level'] == int(e['prefecture_level'])
        for field in ('coordinate_kind', 'coordinate_label', 'coordinate_source_url', 'coordinate_source_name'):
            assert row[field] == e.get(field, ''), (e['id'], field)
    if args.check_sources:
        snapshots = {}
        for e in official:
            url = e['source_url']
            if url not in snapshots:
                cache = args.source_cache / (hashlib.sha256(url.encode()).hexdigest() + '.html') if args.source_cache else None
                if cache and cache.exists():
                    text = cache.read_text()
                else:
                    time.sleep(.3)
                    response = requests.get(url, timeout=30, headers={'User-Agent': 'TokusanMap/1.0 (source verification)'})
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    text = response.text
                    if cache:
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        cache.write_text(text)
                snapshots[url] = normalize(text)
            body = snapshots[url]
            if e['source_kind'] in ('gi', 'traditional', 'cuisine', 'forestry'):
                # The full display label may include synonymous names separated by a slash.
                name = re.split('[／/]', e['label'])[0]
                assert normalize(name) in body, f'Name missing: {e["label"]}'
            assert normalize(e['production_area']) in body, f'Area missing: {e["label"]}'
            if e.get('ingredients'):
                assert normalize(e['ingredients']) in body, f'Ingredients missing: {e["label"]}'
            if e.get('source_classification'):
                assert normalize(e['source_classification']) in body, f'Classification missing: {e["label"]}'
            if e.get('maker'):
                assert normalize(e['maker']) in body, f'Maker missing: {e["label"]}'
        print(f'Official source snapshots checked: {len(snapshots)} pages / {len(official)} items')
    print(f'Catalog OK: {len(rows)} items, {len(counts)} prefectures, minimum {min(counts.values())} per prefecture')
    print('Categories:', dict(sorted(collections.Counter(r['category'] for r in rows.values()).items())))
    print('Region scopes:', dict(collections.Counter(r['region_scope'] for r in rows.values())))


if __name__ == '__main__':
    main()
