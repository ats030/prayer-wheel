#!/usr/bin/env python3
"""Map geological natural monuments to Wikidata items and Japanese Wikipedia articles.

Writes data/geo/wikidata.json: {"401/00003511": {"qid": "Q1", "title": "記事名", "via": "p4275"}}.
A Wikidata item whose P4275 (Japanese Database of National Cultural Properties ID) equals the
monument's category/number is trusted. Otherwise a Japanese Wikipedia article whose title equals
the monument name is a candidate (via "title"); review those before committing the file.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / 'frontend/geo/geosites.json'
OUT = ROOT / 'data/geo/wikidata.json'
USER_AGENT = 'midokoro-map/0.1 (https://midokoro-map.ats030.workers.dev)'
SPARQL = '''SELECT ?item ?id ?article WHERE {
  ?item wdt:P4275 ?id . FILTER(STRSTARTS(?id, "401/"))
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://ja.wikipedia.org/> . }
}'''


def heritage_key(source_url: str) -> str | None:
    """'https://kunishitei.bunka.go.jp/heritage/detail/401/00003511' -> '401/00003511'."""
    match = re.search(r'/heritage/detail/(\d+/\d+)', source_url or '')
    return match.group(1) if match else None


def match_p4275(features: list, bindings: list) -> dict:
    """Map each feature's heritage_key to the Wikidata item whose P4275 equals it.

    features: GeoJSON features; properties.source_url gives the key.
    bindings: SPARQL JSON bindings with item.value (entity URI), id.value (P4275) and optional
    article.value (https://ja.wikipedia.org/wiki/<percent-encoded title>).
    Returns {key: {"qid": "Q…", "title": "decoded title with spaces" or None, "via": "p4275"}}.
    Keys bound to more than one distinct item are left out.
    """
    raise NotImplementedError


def title_candidates(features: list, matched: dict, pages: dict) -> dict:
    """Propose an article for each feature whose key is not in `matched`.

    pages: {monument name: page} where page is a Japanese Wikipedia API page (formatversion=2)
    after redirects, e.g. {"title": "…", "pageprops": {"wikibase_item": "Q1"}} or {"missing": True}.
    A page qualifies only if it is not missing, is not a disambiguation page and has a wikibase_item.
    Returns {key: {"qid": wikibase_item, "title": page title, "via": "title"}}.
    """
    raise NotImplementedError


def get_json(url: str, params: dict) -> dict:
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_bindings() -> list:
    return get_json('https://query.wikidata.org/sparql', {'query': SPARQL, 'format': 'json'})['results']['bindings']


def fetch_pages(names: list) -> dict:
    """Resolve names to pages, following normalization and redirects."""
    pages = {}
    for start in range(0, len(names), 50):
        batch = names[start:start + 50]
        query = get_json('https://ja.wikipedia.org/w/api.php', {'action': 'query', 'titles': '|'.join(batch), 'redirects': 1, 'prop': 'pageprops',
                                                                 'ppprop': 'wikibase_item|disambiguation', 'format': 'json', 'formatversion': 2})['query']
        alias = {item['from']: item['to'] for item in query.get('normalized', []) + query.get('redirects', [])}
        by_title = {page['title']: page for page in query.get('pages', [])}
        for name in batch:
            title = name
            while title in alias:
                title = alias[title]
            if title in by_title:
                pages[name] = by_title[title]
    return pages


def main():
    features = json.loads(SITES.read_text())['features']
    matched = match_p4275(features, fetch_bindings())
    rest = [f['properties']['name'] for f in features if heritage_key(f['properties']['source_url']) not in matched]
    proposed = title_candidates(features, matched, fetch_pages(rest))
    OUT.write_text(json.dumps(dict(sorted({**matched, **proposed}.items())), ensure_ascii=False, indent=1) + '\n')
    print(f'{len(features)} monuments: {len(matched)} by P4275, {len(proposed)} by title (review these)', file=sys.stderr)
    for key, value in sorted(proposed.items()):
        print(f'{key}\t{value["qid"]}\t{value["title"]}')


if __name__ == '__main__':
    main()
