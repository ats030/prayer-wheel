#!/usr/bin/env python3
"""Wikidata SPARQLで日本の祭りを網羅的に発見し、新規候補を洗い出す。

import_wikimedia_festivals.py はWikipediaの
「Category:{都道府県}の祭り」を起点に発見するため、カテゴリ付けが
漏れているアイテムを取りこぼす。本スクリプトはWikidataの
P31/P279* wd:Q132241 (festival及びそのサブクラス全て) をSPARQLで
直接検索し、日本に関連する全アイテムを取得することで網羅性を補う。

出力フォーマットはimport_wikimedia_festivals.pyのbuild_candidatesに
揃えている(qid, label_ja, label_en, prefecture, latitude, longitude,
description, date, wikipedia_title, coordinate_source)。
"""

import argparse
import json
import re
import time
from pathlib import Path

import requests

try:
    import enrich_wikidata_dates as date_enricher
    import apply_verified_occurrences as verified_dates
    import apply_verified_venues as verified_venues
    import validate_prefecture_coordinates as coordinate_validator
except ModuleNotFoundError:  # unittest imports this file from the repository root
    from scripts import enrich_wikidata_dates as date_enricher
    from scripts import apply_verified_occurrences as verified_dates
    from scripts import apply_verified_venues as verified_venues
    from scripts import validate_prefecture_coordinates as coordinate_validator

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "OmatsuriMap/1.0 (https://github.com/ats030/ikimono-note)"
EXCLUDED_TITLE = re.compile(r"(?:神社|神宮|寺|公園|博物館|資料館|協会)(?:\s*\([^)]*\))?$")

SPARQL_QUERY = """
SELECT DISTINCT ?item WHERE {
  ?item wdt:P31/wdt:P279* wd:Q132241 .
  {
    ?item wdt:P17 wd:Q17 .
  } UNION {
    ?item wdt:P131 ?admin .
    ?admin wdt:P17 wd:Q17 .
  } UNION {
    ?item wdt:P276 ?venue .
    ?venue wdt:P17 wd:Q17 .
  }
}
"""


def request_json(session, url, params, retries=3, timeout=120):
    for attempt in range(retries + 1):
        response = session.get(url, params=params, timeout=timeout)
        if response.status_code == 200:
            return response.json()
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
        if attempt == retries:
            response.raise_for_status()
        time.sleep(int(response.headers.get("Retry-After", 2**attempt)))
    raise RuntimeError("unreachable")


def batches(items, size=50):
    items = list(items)
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def sparql_qids(session):
    data = request_json(
        session,
        SPARQL_ENDPOINT,
        {"query": SPARQL_QUERY, "format": "json"},
    )
    qids = set()
    for row in data.get("results", {}).get("bindings", []):
        uri = row.get("item", {}).get("value", "")
        if uri.startswith("http://www.wikidata.org/entity/"):
            qids.add(uri.rsplit("/", 1)[-1])
    return qids


def coordinate(entity):
    for claim in entity.get("claims", {}).get("P625", []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if "latitude" in value and "longitude" in value:
            return value["latitude"], value["longitude"]
    return None


def related_qids(entity, property_id):
    result = []
    for claim in entity.get("claims", {}).get(property_id, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if value.get("entity-type") == "item" and value.get("id"):
            result.append(value["id"])
    return result


def resolved_coordinate(entity, places):
    direct = coordinate(entity)
    if direct:
        return (*direct, "festival")
    for property_id, source in (("P276", "venue"), ("P131", "administrative_area")):
        for qid in related_qids(entity, property_id):
            found = coordinate(places.get(qid, {}))
            if found:
                return (*found, source)
    return None


def fetch_entities(session, qids, props="labels|descriptions|claims|sitelinks"):
    result = {}
    qids = sorted({qid for qid in qids if qid})
    for batch in batches(qids):
        data = request_json(session, WIKIDATA_API, {
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": props, "languages": "ja|en", "sitefilter": "jawiki",
            "format": "json", "formatversion": "2",
        })
        result.update(data.get("entities", {}))
    return result


def jawiki_title(entity):
    return entity.get("sitelinks", {}).get("jawiki", {}).get("title")


def build_candidates(entities, places, features, existing_qids):
    candidates = []
    for qid, entity in entities.items():
        if qid in existing_qids:
            continue
        title = jawiki_title(entity)
        if not title:
            continue
        if EXCLUDED_TITLE.search(title):
            continue
        coords = resolved_coordinate(entity, places)
        if not coords:
            continue
        latitude, longitude, coordinate_source = coords
        if not (20 <= latitude <= 46 and 122 <= longitude <= 154):
            continue
        prefecture = coordinate_validator.containing_prefecture(longitude, latitude, features)
        if not prefecture:
            continue
        labels = entity.get("labels", {})
        descriptions = entity.get("descriptions", {})
        candidates.append({
            "qid": qid,
            "label_ja": labels.get("ja", {}).get("value") or title,
            "label_en": labels.get("en", {}).get("value", ""),
            "prefecture": prefecture,
            "latitude": latitude,
            "longitude": longitude,
            "description": descriptions.get("ja", {}).get("value", ""),
            "date": "日付未定",
            "wikipedia_title": title,
            "coordinate_source": coordinate_source,
        })
    return sorted(candidates, key=lambda item: (item["prefecture"], item["label_ja"]))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "frontend/festivals.json")
    parser.add_argument("--merge", action="store_true", help="append candidates to the data file")
    args = parser.parse_args()
    existing = json.loads(args.data.read_text(encoding="utf-8"))
    existing_qids = {item["qid"] for item in existing if item.get("qid")}

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    print("querying Wikidata SPARQL for Japanese festivals...", flush=True)
    qids = sparql_qids(session)
    print(f"SPARQL hits: {len(qids)}", flush=True)

    entities = fetch_entities(session, qids)
    print(f"entities fetched: {len(entities)}", flush=True)

    place_qids = {
        qid
        for entity in entities.values()
        for property_id in ("P276", "P131")
        for qid in related_qids(entity, property_id)
    }
    places = fetch_entities(session, place_qids, props="claims")
    print(f"place entities fetched: {len(places)}", flush=True)

    print("fetching prefecture boundaries...", flush=True)
    features = coordinate_validator.fetch_features()

    candidates = build_candidates(entities, places, features, existing_qids)
    print(f"new geolocated festivals with jawiki article: {len(candidates)}")

    if args.merge:
        merged = existing + candidates
        missing_qids = {item["qid"] for item in merged if item.get("qid")} - entities.keys()
        entities.update(fetch_entities(session, missing_qids))
        calendar_qids = {qid for entity in entities.values() for qid in date_enricher.p837_qids(entity)}
        calendar_entities = fetch_entities(session, calendar_qids)
        schedules = date_enricher.schedules_by_festival(entities, calendar_entities)
        dated = date_enricher.enrich(merged, schedules)
        with_occurrences = verified_dates.apply_occurrences(dated)
        with_venues = verified_venues.apply_venues(with_occurrences)
        validated = coordinate_validator.apply_coordinate_prefectures(with_venues, features)
        write_json(args.data, validated)
        print(f"merged total: {len(merged)}; annual schedules: {len(schedules)}")
    else:
        print("dry run; pass --merge to update the data file")


if __name__ == "__main__":
    main()
