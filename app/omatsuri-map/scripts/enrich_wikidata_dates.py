#!/usr/bin/env python3
"""Wikidata P837 から毎年の開催日・曜日規則を安全に補完する。"""

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "OmatsuriMap/1.0 (https://github.com/ats030/ikimono-note)"
WEEKDAYS = {"月": 1, "火": 2, "水": 3, "木": 4, "金": 5, "土": 6, "日": 7}


def batches(items, size=50):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def request_entities(session, qids, props):
    result = {}
    for batch in batches(sorted(set(qids))):
        for attempt in range(4):
            response = session.get(
                WIKIDATA_API,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": props,
                    "languages": "ja|en",
                    "format": "json",
                    "formatversion": "2",
                },
                timeout=30,
            )
            if response.status_code == 200:
                result.update(response.json().get("entities", {}))
                break
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
            if attempt == 3:
                response.raise_for_status()
            time.sleep(int(response.headers.get("Retry-After", 2**attempt)))
    return result


def p837_qids(entity):
    result = []
    for claim in entity.get("claims", {}).get("P837", []):
        if claim.get("rank") == "deprecated":
            continue
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and value.get("id"):
            result.append(value["id"])
    return result


def parse_calendar_item(label):
    match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", label)
    if match:
        month, day = map(int, match.groups())
        try:
            date(2000, month, day)
        except ValueError:
            return None
        return {"kind": "fixed", "month": month, "day": day, "label": label}
    if label == "大晦日":
        return {"kind": "fixed", "month": 12, "day": 31, "label": label}
    match = re.fullmatch(r"(\d{1,2})月の第([1-5])([月火水木金土日])曜日", label)
    if match:
        month, ordinal, weekday = match.groups()
        return {
            "kind": "nth_weekday", "month": int(month), "ordinal": int(ordinal),
            "weekday": WEEKDAYS[weekday], "label": label,
        }
    match = re.fullmatch(r"(\d{1,2})月の最終([月火水木金土日])曜日", label)
    if match:
        month, weekday = match.groups()
        return {"kind": "last_weekday", "month": int(month), "weekday": WEEKDAYS[weekday], "label": label}
    return None


def group_fixed_dates(items):
    fixed = sorted((item for item in items if item["kind"] == "fixed"), key=lambda item: (item["month"], item["day"]))
    grouped = []
    for item in fixed:
        current = date(2000, item["month"], item["day"])
        if grouped and (current - grouped[-1]["_last"]).days == 1:
            grouped[-1]["end"] = f"{item['month']:02d}-{item['day']:02d}"
            grouped[-1]["_last"] = current
        else:
            grouped.append({"kind": "fixed", "start": f"{item['month']:02d}-{item['day']:02d}", "end": f"{item['month']:02d}-{item['day']:02d}", "_last": current})
    for item in grouped:
        item.pop("_last")
    return grouped + [item for item in items if item["kind"] != "fixed"]


def schedules_by_festival(festival_entities, calendar_entities):
    result = {}
    for qid, entity in festival_entities.items():
        linked = p837_qids(entity)
        if not linked:
            continue
        parsed = []
        for calendar_qid in linked:
            labels = calendar_entities.get(calendar_qid, {}).get("labels", {})
            label = labels.get("ja", {}).get("value", "")
            item = parse_calendar_item(label)
            if item is None:
                parsed = []
                break
            parsed.append(item)
        if parsed:
            source = f"https://www.wikidata.org/wiki/{qid}#P837"
            result[qid] = [{**item, "source": source} for item in group_fixed_dates(parsed)]
    return result


def enrich(rows, schedules):
    updated = []
    for row in rows:
        item = dict(row)
        item.pop("annual_schedule", None)
        if item.get("qid") in schedules:
            item["annual_schedule"] = schedules[item["qid"]]
        updated.append(item)
    return updated


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "frontend/festivals.json")
    args = parser.parse_args()
    rows = json.loads(args.data.read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    festival_entities = request_entities(session, [row["qid"] for row in rows if re.fullmatch(r"Q[1-9][0-9]*", row.get("qid", ""))], "claims")
    calendar_qids = {qid for entity in festival_entities.values() for qid in p837_qids(entity)}
    calendar_entities = request_entities(session, calendar_qids, "labels")
    schedules = schedules_by_festival(festival_entities, calendar_entities)
    write_json(args.data, enrich(rows, schedules))
    print(f"annual schedules: {len(schedules)} / {len(rows)} festivals")


if __name__ == "__main__":
    main()
