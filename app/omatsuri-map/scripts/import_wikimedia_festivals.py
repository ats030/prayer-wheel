#!/usr/bin/env python3
"""Import geolocated Japanese festivals discovered through Wikimedia projects."""

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

WIKIPEDIA_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "OmatsuriMap/1.0 (https://github.com/ats030/ikimono-note)"
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
EXCLUDED_TITLE = re.compile(r"(?:神社|神宮|寺|公園|博物館|資料館|協会)(?:\s*\([^)]*\))?$")


def request_json(session, url, params, retries=3):
    for attempt in range(retries + 1):
        response = session.get(url, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
        if attempt == retries:
            response.raise_for_status()
        time.sleep(int(response.headers.get("Retry-After", 2**attempt)))
    raise RuntimeError("unreachable")


def batches(items, size=50):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def discover_titles(session):
    title_prefectures = {}
    for prefecture in PREFECTURES:
        continuation = {}
        while True:
            params = {
                "action": "query", "list": "categorymembers",
                "cmtitle": f"Category:{prefecture}の祭り", "cmnamespace": "0",
                "cmlimit": "500", "format": "json", "formatversion": "2",
                **continuation,
            }
            data = request_json(session, WIKIPEDIA_API, params)
            for page in data.get("query", {}).get("categorymembers", []):
                title_prefectures.setdefault(page["title"], set()).add(prefecture)
            if "continue" not in data:
                break
            continuation = data["continue"]
    return title_prefectures


def fetch_qids(session, titles):
    result = {}
    for batch in batches(sorted(titles)):
        data = request_json(session, WIKIPEDIA_API, {
            "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
            "titles": "|".join(batch), "format": "json", "formatversion": "2",
        })
        for page in data.get("query", {}).get("pages", []):
            qid = page.get("pageprops", {}).get("wikibase_item")
            if qid:
                result[page["title"]] = qid
    return result


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


def fetch_entities(session, qids):
    result = {}
    for batch in batches(sorted(set(qids))):
        data = request_json(session, WIKIDATA_API, {
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "labels|descriptions|claims", "languages": "ja|en",
            "format": "json", "formatversion": "2",
        })
        result.update(data.get("entities", {}))
    return result


def build_candidates(title_prefectures, title_qids, entities, places, existing_qids):
    candidates = []
    for title in sorted(title_qids):
        qid = title_qids[title]
        prefectures = title_prefectures[title]
        entity = entities.get(qid, {})
        coords = resolved_coordinate(entity, places)
        if qid in existing_qids or len(prefectures) != 1 or not coords or EXCLUDED_TITLE.search(title):
            continue
        latitude, longitude, coordinate_source = coords
        if not (20 <= latitude <= 46 and 122 <= longitude <= 154):
            continue
        labels = entity.get("labels", {})
        descriptions = entity.get("descriptions", {})
        candidates.append({
            "qid": qid,
            "label_ja": title,
            "label_en": labels.get("en", {}).get("value", ""),
            "prefecture": next(iter(prefectures)),
            "latitude": latitude,
            "longitude": longitude,
            "description": descriptions.get("ja", {}).get("value", ""),
            "date": "日付未定",
            "wikipedia_title": title,
            "coordinate_source": coordinate_source,
        })
    order = {name: index for index, name in enumerate(PREFECTURES)}
    return sorted(candidates, key=lambda item: (order[item["prefecture"]], item["label_ja"]))


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
    managed_sources = {"festival", "venue", "administrative_area"}
    base = [item for item in existing if item.get("coordinate_source") not in managed_sources]
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    title_prefectures = discover_titles(session)
    print(f"category pages: {len(title_prefectures)}", flush=True)
    title_qids = fetch_qids(session, title_prefectures)
    print(f"pages with Wikidata IDs: {len(title_qids)}", flush=True)
    entities = fetch_entities(session, title_qids.values())
    place_qids = {
        qid
        for entity in entities.values()
        for property_id in ("P276", "P131")
        for qid in related_qids(entity, property_id)
    }
    places = fetch_entities(session, place_qids)
    candidates = build_candidates(title_prefectures, title_qids, entities, places, {item["qid"] for item in base})
    print(f"new geolocated festivals: {len(candidates)}")
    if args.merge:
        merged = base + candidates
        missing_qids = {item["qid"] for item in merged if item.get("qid")} - entities.keys()
        entities.update(fetch_entities(session, missing_qids))
        calendar_qids = {qid for entity in entities.values() for qid in date_enricher.p837_qids(entity)}
        calendar_entities = fetch_entities(session, calendar_qids)
        schedules = date_enricher.schedules_by_festival(entities, calendar_entities)
        dated = date_enricher.enrich(merged, schedules)
        with_occurrences = verified_dates.apply_occurrences(dated)
        with_venues = verified_venues.apply_venues(with_occurrences)
        validated = coordinate_validator.apply_coordinate_prefectures(
            with_venues, coordinate_validator.fetch_features()
        )
        write_json(args.data, validated)
        print(f"merged total: {len(merged)}; annual schedules: {len(schedules)}")
    else:
        print("dry run; pass --merge to update the data file")


if __name__ == "__main__":
    main()
