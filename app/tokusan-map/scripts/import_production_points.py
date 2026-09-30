#!/usr/bin/env python3
"""Create auditable production representative points from MLIT P05-22.

Run with --archive pointing to the official nationwide P05-22_GML.zip.
No network access, geocoding, or production-area rewriting is performed.
"""
import argparse
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFECTURES = ('北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 '
               '埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 '
               '岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 '
               '鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 '
               '佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県').split()
SOURCE = 'https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-2022.html'


def normalize(text):
    """Fold compatibility forms such as Kangxi radicals (⼤⽥市) into ordinary kanji."""
    return unicodedata.normalize('NFKC', text)


def explicitly_prefecture_wide(area, prefecture):
    text = normalize(area).replace(prefecture, '県').replace(' ', '')
    return bool(re.search(r'(?:県|都|道|府)内全域|(?:県|都|道|府)全域|全県|(?:^|[、,（(])全域(?:$|[、,）)])', text))


def first_municipality(area, names):
    """Use source order, never a coordinate or product-name inference."""
    area = normalize(area)
    hits = [(area.index(name), -len(name), name) for name in names if name in area]
    return min(hits)[2] if hits else None


def first_place(area, prefecture):
    """The first place name in source order, e.g. 秩父地域 in 秩父地域、本庄市."""
    text = normalize(area).replace(prefecture, '').strip()
    return re.split(r'[、,・/／（(\s]', text)[0]


def read_offices(archive):
    offices = {}
    with zipfile.ZipFile(archive) as nationwide:
        for filename in nationwide.namelist():
            if not re.fullmatch(r'P05-22_\d{2}_GML.zip', filename):
                continue
            with zipfile.ZipFile(io.BytesIO(nationwide.read(filename))) as local:
                geojson = next(n for n in local.namelist() if n.endswith('.geojson'))
                for feature in json.loads(local.read(geojson))['features']:
                    props = feature['properties']
                    if str(props['P05_002']) != '1':
                        continue  # Headquarters only; no branch or community hall.
                    match = re.match(r'^(.+?[市区町村])(?:役所|役場)', props['P05_003'])
                    if not match:
                        continue
                    prefecture = PREFECTURES[int(str(props['P05_001'])[:2]) - 1]
                    key = (prefecture, match[1])
                    lng, lat = feature['geometry']['coordinates']
                    offices.setdefault(key, []).append({
                        'municipality': match[1], 'office': props['P05_003'],
                        'address': props['P05_004'], 'municipality_code': props['P05_001'],
                        'lat': lat, 'lng': lng,
                    })
    # A duplicate whose address names another municipality is a source error
    # (茨城町役場 under 土浦市); other ties are not resolved by arbitrary input order.
    resolved = {}
    for key, values in offices.items():
        if len(values) > 1:
            values = [v for v in values if v['address'].startswith(key[1])]
        if len(values) == 1:
            resolved[key] = values[0]
    return resolved


def accepted_areas():
    areas = json.loads((ROOT / 'data/named_areas.json').read_text())['areas']
    return {(a['prefecture'], a['text']): a for a in areas if a['decision'] == 'accept'}


def apply_points(items, registry):
    """Apply approved coordinates without changing any production evidence."""
    by_id = {item['id']: item for item in items}
    named = accepted_areas()
    for item_id, point in registry['points'].items():
        assert item_id in by_id, f'Unknown production point: {item_id}'
        item = by_id[item_id]
        assert point['prefecture'] == item['prefecture'], item_id
        # An alias point names its source text; the registry keeps the alias evidence URL.
        assert point.get('source_text', point['municipality']) in normalize(item['production_area']), item_id
        assert not explicitly_prefecture_wide(item['production_area'], item['prefecture']), item_id
        if point['kind'] == 'named_area_office':
            # A reviewed area name (named_areas.json) that is the first place in the source.
            assert point['source_text'] == first_place(item['production_area'], item['prefecture']), item_id
            assert point['selection'] == 'first_place_in_source', item_id
            area = named.get((point['prefecture'], point['source_text']))
            assert area and area['municipality'] == point['municipality'], item_id
        else:
            assert ('source_text' in point) == ('alias_source_url' in point), item_id
            assert point['kind'] == 'municipality_office', item_id
            assert point['selection'] == 'first_municipality_in_source', item_id
        assert point['office'].startswith(point['municipality']), item_id
        assert 20 < point['lat'] < 46 and 122 < point['lng'] < 154, item_id
    return [dict(item, lat=point['lat'], lng=point['lng'], prefecture_level=False,
                 city=point['municipality'], coordinate_kind=point['kind'],
                 coordinate_label=point['source_text'] if point['kind'] == 'named_area_office' else point['municipality'],
                 coordinate_source_url=registry['source_url'],
                 coordinate_source_name=registry['source_name'])
            if (point := registry['points'].get(item['id'])) else dict(item) for item in items]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    offices = read_offices(args.archive)
    aliases = json.loads((ROOT / 'data/municipality_aliases.json').read_text())['aliases']
    named = accepted_areas()
    items = json.loads((ROOT / 'data/official.json').read_text())
    points = {}
    for item in items:
        if explicitly_prefecture_wide(item['production_area'], item['prefecture']):
            continue
        area = named.get((item['prefecture'], first_place(item['production_area'], item['prefecture'])))
        if area:
            points[item['id']] = dict(offices[(item['prefecture'], area['municipality'])],
                                      prefecture=item['prefecture'], kind='named_area_office',
                                      selection='first_place_in_source', source_text=area['text'])
            continue
        renamed = {a['text']: a for a in aliases if a['prefecture'] == item['prefecture']}
        names = [name for pref, name in offices if pref == item['prefecture']]
        name = first_municipality(item['production_area'], names + list(renamed))
        if not name:
            continue
        alias = renamed.get(name)
        point = dict(offices[(item['prefecture'], alias['municipality'] if alias else name)],
                     prefecture=item['prefecture'], kind='municipality_office',
                     selection='first_municipality_in_source')
        if alias:
            point.update(source_text=name, alias_source_url=alias['source_url'])
        points[item['id']] = point
    output = {
        'source_name': '国土交通省 国土数値情報 市町村役場等及び公的集会施設（2022年4月）',
        'source_url': SOURCE, 'license': 'CC BY 4.0', 'source_checked_at': '2026-09-29',
        'archive_sha256': hashlib.sha256(args.archive.read_bytes()).hexdigest(),
        'processing': '施設分類1の単一役場を産地記載順で選択。旧町名・誤記は municipality_aliases.json で現行市町村へ対応。最初の地名が named_areas.json で採用した地域名なら同名市町村の役場を地域代表点とする。産地の代表点として加工。',
        'points': points,
    }
    (ROOT / 'data/production_points.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(f'Production representative points: {len(points)} / {len(items)}')


if __name__ == '__main__':
    main()
