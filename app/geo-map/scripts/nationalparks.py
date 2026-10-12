"""Build nationalpark in geo.db from the MOE catalogue and EADAS public area layer.

Cache contains source data only, never anonymous session credentials.
"""
import argparse
from collections import defaultdict
from datetime import date
import html
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlparse

from geodb import replace_tables
from geoparks import display_boundary

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / 'cache/geo-map/nationalparks'
CATALOGUE = 'https://www.env.go.jp/park/parks/'
EADAS = 'https://eadas.env.go.jp'
SOURCE = EADAS + '/eiadb/ebidbs/Service/About?title=Gis'
USER_AGENT = 'MidokoroMap/1.0 (https://github.com/ats030)'


def text(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', value))).strip()


def catalogue(page):
    parks = {}
    # Each official list card contains its own nested data list. Repeated Setonaikai
    # cards in different regions are deduplicated by the official park URL.
    for block in re.split(r'<li\b[^>]*class="item item-', page)[1:]:
        name = re.search(r'<span class="name">(.*?)</span>', block, re.S)
        if not name:
            continue  # Navigation and footer use the same item-* class prefix.
        link = re.search(r'<a href="([^\"]+)"', block)
        fields = {key: text(value) for key, value in re.findall(r'<li class="data__(date|area|region)">(.*?)</li>', block, re.S)}
        if not link or set(fields) != {'date', 'area', 'region'}:
            raise ValueError('Incomplete official park card')
        url = urljoin(CATALOGUE, html.unescape(link.group(1)))
        if urlparse(url).hostname != 'www.env.go.jp':
            raise ValueError('Unexpected catalogue source host')
        slug = urlparse(url).path.split('/')[-2]
        item = {'slug': slug, 'name': text(name.group(1)), 'source_url': url,
                'designated': fields['date'].removeprefix('指定：'),
                'area_label': fields['area'].removeprefix('面積：'),
                'prefectures': fields['region']}
        if slug in parks and parks[slug] != item:
            raise ValueError('Conflicting duplicate park card: ' + slug)
        parks[slug] = item
    if not parks:
        raise ValueError('Official park catalogue is empty')
    return parks


def checked_response(response):
    if response.status_code != 200:
        raise ValueError(f'Source HTTP {response.status_code}')
    if len(response.content) > 64 * 1024 * 1024:
        raise ValueError('Source response exceeds 64 MB')
    return response


def fetch_sources(cache, refresh=False):
    import requests
    cache.mkdir(parents=True, exist_ok=True)
    names = ['catalogue.html', 'areas.json', 'source.json', 'meta.json']
    if not refresh and all((cache / name).exists() for name in names):
        page = (cache / names[0]).read_text()
        areas, source, meta = [json.loads((cache / name).read_text()) for name in names[1:]]
        validate_area_snapshot(areas, meta)
        return page, areas, source, meta
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT, 'Referer': EADAS + '/'})
    page = checked_response(session.get(CATALOGUE, timeout=60)).content.decode('utf-8')
    checked_response(session.get(EADAS + '/eiadb/ebidbs/Service/', timeout=60))
    checked_response(session.get(EADAS + '/eiadb/ebidbs/Service/Agreement', params={'page': 'GisMap'}, timeout=60))
    settings = checked_response(session.post(EADAS + '/eiadb/ebidbs/Service/GisSetting', data=b'', timeout=60)).json()
    def find(nodes):
        if isinstance(nodes, dict):
            if nodes.get('text') == '自然公園区域（国立公園）':
                return nodes
            children = nodes.values()
        elif isinstance(nodes, list):
            children = nodes
        else:
            return None
        for node in children:
            result = find(node)
            if result:
                return result
    layer = find(settings['jkGroups'])
    if not layer:
        raise ValueError('National park area setting not found')
    detail = layer['jkDetail']
    distributor = settings['distributors'][detail['distributor']]
    base = distributor['url'] + detail['service'] + '/MapServer'
    if urlparse(base).hostname != 'eadas.env.go.jp':
        raise ValueError('Unexpected boundary source host')
    token = distributor['key']
    def query(path, **params):
        try:
            response = checked_response(session.get(base + path, params={'token': token, **params}, timeout=180))
        except requests.RequestException:
            raise ValueError('Public area request failed') from None
        result = response.json()
        if 'error' in result:
            raise ValueError('Public area query failed')
        return result
    service = query('', f='json')
    area_layers = [item['id'] for item in service['layers'] if item['name'] == '区域（国立公園）']
    if len(area_layers) != 1:
        raise ValueError('Expected exactly one national park area layer')
    path = '/' + str(area_layers[0]) + '/query'
    ids = sorted(query(path, f='json', where='1=1', returnIdsOnly='true')['objectIds'])
    features = []
    for start in range(0, len(ids), 50):
        time.sleep(1)
        batch = query(path, f='geojson', objectIds=','.join(map(str, ids[start:start+50])),
                      outFields='*', returnGeometry='true', outSR=4326)
        if batch.get('exceededTransferLimit') or len(batch.get('features', [])) != len(ids[start:start+50]):
            raise ValueError('Incomplete national park area batch')
        if {feature['id'] for feature in batch['features']} != set(ids[start:start+50]):
            raise ValueError('National park area IDs do not match the requested batch')
        features.extend(batch['features'])
    areas = {'type': 'FeatureCollection', 'features': features}
    source = {'url': base + '/' + str(area_layers[0]), 'metadata': layer['meta']}
    meta = {'fetched': date.today().isoformat(), 'feature_count': len(ids), 'object_ids': ids}
    validate_area_snapshot(areas, meta)
    # Write source snapshots only after every query succeeds.
    values = [page, json.dumps(areas, ensure_ascii=False), json.dumps(source, ensure_ascii=False), json.dumps(meta)]
    for name, value in zip(names, values):
        (cache / name).write_text(value)
    return page, areas, source, meta


def validate_area_snapshot(areas, meta):
    features = areas.get('features', [])
    if not features or meta.get('feature_count') != len(features):
        raise ValueError('Cached national park area count is incomplete; refresh the snapshot')
    ids = [feature.get('id') for feature in features]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError('National park area IDs are missing or duplicated')
    if 'object_ids' in meta and set(ids) != set(meta['object_ids']):
        raise ValueError('Cached national park area IDs are incomplete; refresh the snapshot')


def park_rows(parks, areas, source, fetched):
    from shapely.geometry import shape, mapping
    from shapely import unary_union
    expected = {park['name'].removesuffix('国立公園'): park for park in parks.values()}
    if len(expected) != len(parks):
        raise ValueError('Duplicate official park names')
    grouped = defaultdict(list)
    origins = defaultdict(set)
    repairs = defaultdict(int)
    for feature in areas['features']:
        props = feature['properties']
        name = str(props.get('名称', '')).strip().removesuffix('国立公園')
        if name not in expected:
            raise ValueError('Unmatched area park: ' + name)
        geometry = shape(feature['geometry'])
        if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty:
            raise ValueError('Invalid source area: ' + name)
        if not geometry.is_valid:
            geometry = repair_area(geometry)
            repairs[name] += 1
        grouped[name].append(geometry)
        origins[name].add(str(props.get('SA10_1_012', '')).strip())
    if set(grouped) != set(expected):
        raise ValueError('Parks without areas: ' + ','.join(sorted(set(expected) - set(grouped))))
    rows = []
    for park in sorted(parks.values(), key=lambda item: item['slug']):
        name = park['name'].removesuffix('国立公園')
        area = unary_union(grouped[name])
        display = display_boundary(area)
        if not display.is_valid or display.is_empty:
            raise ValueError('Invalid display area: ' + park['name'])
        rows.append((park['slug'], park['name'], park['source_url'], park['designated'],
                     park['area_label'], park['prefectures'], source['url'], fetched,
                     source['metadata']['整備年度'], json.dumps(sorted(origins[name]), ensure_ascii=False),
                     json.dumps(mapping(display), separators=(',', ':')), repairs[name]))
    return rows


def repair_area(geometry):
    """Repair self-touching source rings only when the polygon area stays equivalent."""
    from shapely import make_valid
    from shapely.geometry import MultiPolygon
    original_area = geometry.area
    fixed = make_valid(geometry)
    def polygons(part):
        if part.geom_type == 'Polygon':
            return [part]
        if hasattr(part, 'geoms'):
            return [polygon for child in part.geoms for polygon in polygons(child)]
        return []
    result = MultiPolygon(polygons(fixed))
    if (original_area <= 0 or result.is_empty or not result.is_valid or
            abs(result.area - original_area) > max(1e-9, original_area * 1e-6)):
        raise ValueError('Source ring repair would change the area; manual review required')
    return result


def build(cache, out, refresh=False):
    page, areas, source, meta = fetch_sources(cache, refresh)
    parks = catalogue(page)
    rows = park_rows(parks, areas, source, meta['fetched'])
    replace_tables(out, '''create table nationalpark(
        slug text primary key, name text not null, source_url text not null, designated text not null,
        area_label text not null, prefectures text not null, boundary_source text not null, fetched text not null,
        data_year text not null, provenance text not null, display_geometry text not null,
        geometry_repairs integer not null);''',
        {'nationalpark': rows}, {'nationalpark_source': SOURCE, 'nationalpark_built': date.today().isoformat(),
                                'nationalpark_catalogue': CATALOGUE})
    return {'parks': len(rows), 'source_features': len(areas['features']), 'fetched': meta['fetched'],
            'repaired_source_features': sum(row[-1] for row in rows)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--out', type=Path, default=ROOT / 'data/geo.db')
    args = parser.parse_args()
    print(json.dumps(build(args.cache, args.out, args.refresh), ensure_ascii=False))
