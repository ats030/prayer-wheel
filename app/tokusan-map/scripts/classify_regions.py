"""Source-based regional membership, independent of representative coordinates."""
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from import_production_points import PREFECTURES, explicitly_prefecture_wide

ROOT = Path(__file__).resolve().parent.parent


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def load_regions():
    definitions = json.loads((ROOT / 'data/regions.json').read_text())
    assert {p['prefecture'] for p in definitions} == set(PREFECTURES)
    assert len(definitions) == 47
    ids = set()
    for pref in definitions:
        assert urlparse(pref['source_url']).scheme == 'https'
        assert pref['source_name'] and pref['source_checked_at']
        assert pref['regions']
        for region in pref['regions']:
            assert region['id'] not in ids and region['label'] and region['aliases']
            assert region['id'].startswith(pref['code'] + '-')
            assert all(normalize(a) for a in region['aliases'])
            ids.add(region['id'])
    return definitions


def classify(area, prefecture, definition):
    source = normalize(area)
    if explicitly_prefecture_wide(source, prefecture):
        return [], 'prefecture', '出典に都道府県全域と明記'
    source = source.replace(prefecture, prefecture[-1])
    locality_regions = [normalize(a) for r in definition['regions'] for a in r['aliases']
                        if not re.search(r'[市区町村]$', a)]
    def remove_parent_region(match):
        text = match.group(1)
        # 長岡市（中越地方） describes the city's parent area, not extra origins.
        if any(re.fullmatch(re.escape(a) + r'(?:地方|地域|地区|エリア)?', text)
               for a in locality_regions):
            return ''
        return match.group(0)
    source = re.sub(r'(?<=[市区町村])\(([^()]*)\)', remove_parent_region, source)
    candidates = []
    for region in definition['regions']:
        for alias in region['aliases']:
            word = normalize(alias)
            for match in re.finditer(re.escape(word), source):
                suffix = source[match.end():]
                # A region word embedded in a different proper name is not evidence.
                if not re.search(r'[市区町村]$', word) and suffix and re.match(r'[一-龥ぁ-んァ-ヶ]', suffix):
                    if not re.match(r'(?:地方|地域|地区|エリア|周辺|沿岸|半島|流域|食文化圏|北部|南部|東部|西部)', suffix):
                        continue
                candidates.append((match.start(), match.end(), region['id'], alias))
    hits = {}
    for start, end, region_id, alias in candidates:
        if any(a <= start and end <= b and b - a > end - start for a, b, _, _ in candidates):
            continue  # Prefer 東大阪市 over its substring 大阪市, for example.
        hits.setdefault(region_id, []).append(alias)
    if not hits:
        return [], 'unknown', '出典の産地から採用区分との対応を確認できない'
    ids = [r['id'] for r in definition['regions'] if r['id'] in hits]
    return ids, 'regional', '; '.join(f'{key}: {", ".join(dict.fromkeys(hits[key]))}' for key in ids)


def export_public(definitions):
    public = [dict(pref, regions=[{'id': r['id'], 'label': r['label']} for r in pref['regions']])
              for pref in definitions]
    (ROOT / 'frontend/regions.json').write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n')
