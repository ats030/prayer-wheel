#!/usr/bin/env python3
"""Compare public snapshots and representative live upstream APIs before cutover."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('target')
parser.add_argument('--reference', default='https://midokoro-map-736831430371.asia-northeast1.run.app')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]


def get(origin, path):
    req = urllib.request.Request(origin.rstrip('/') + path, headers={'User-Agent': 'midokoro-map-migration-check/1.0'})
    with urllib.request.urlopen(req, timeout=100) as r:
        return json.load(r)


def pair(path):
    with ThreadPoolExecutor(max_workers=2) as pool:
        return tuple(pool.map(lambda origin: get(origin, path), [args.reference, args.target]))


counts = {}
for kind, collection in [('shiseki', 'shiseki'), ('omatsuri', 'festivals'), ('onsen', 'onsen'), ('tokusan', 'tokusan')]:
    path = f'/api/{kind}/{collection}/'
    expected = json.loads((root / 'cloudflare/assets/_data' / kind / 'list.json').read_text())
    old, new = pair(path)
    assert old == new == expected, f'{kind}: published list differs'
    counts[kind] = len(new)
    row = next(r for r in new if r.get('qid'))
    for suffix in [row['qid'], 'prefecture/' + urllib.parse.quote(row['prefecture'])]:
        old, new = pair(path + suffix)
        assert old == new, f'{kind}: {suffix} differs'
    print(f'{kind}: full list ({len(expected)}), item and prefecture match', flush=True)

results = []
for kind, title, qid in [('onsen', '草津温泉', 'Q3137477'), ('shiseki', '姫路城', 'Q188754'), ('omatsuri', '川越氷川祭', 'Q11019445')]:
    path = f'/api/{kind}/wiki/content?' + urllib.parse.urlencode({'title': title, 'qid': qid})
    old, new = pair(path)
    assert not old.get('sections_unavailable') and not new.get('sections_unavailable'), f'{kind}: transient failure, cutover check cannot pass'
    for key in ['description', 'source_url', 'content_license_url', 'history', 'remains', 'access', 'highlights', 'food', 'efficacy', 'tourism', 'flow']:
        assert old.get(key, {}) == new.get(key, {}), f'{kind}: {key} differs'
    assert bool(old.get('image_url')) == bool(new.get('image_url')), f'{kind}: image unavailable'
    if new.get('image_url'):
        assert new.get('license') and new.get('image_source_url'), f'{kind}: attribution missing'
    results.append({'kind': kind, 'title': title, 'section_match': True, 'attributed_image': bool(new.get('image_url'))})
    print(f'{kind}: Wikipedia description/sections match, attributed image available={bool(new.get("image_url"))}', flush=True)

for qid in ['Q11257243', 'local-5aba329a3305884a']:
    old, new = pair('/api/tokusan/sections/' + qid)
    assert not old.get('sections_unavailable') and not new.get('sections_unavailable'), 'tokusan: transient failure'
    assert old == new, f'tokusan: sections for {qid} differ'
    print(f'tokusan: sections {qid} match', flush=True)

report = {'target': args.target, 'reference': args.reference, 'counts': counts, 'live_wikipedia': results, 'checks': 'full published lists, item/prefecture routes, live Wikipedia sections, official-source and Wikipedia tokusan sections'}
(root / 'artifacts/cloudflare-api-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
