#!/usr/bin/env python3
"""Validate and append an independently reviewed official-source batch.

The qid field remains the API's stable record key. Local keys use local-*, never
pretend to be Wikidata IDs, and must not be changed when an annual edition ends.
No fetching, prose generation, or geocoding is performed by this importer.
"""
import argparse
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlparse

try:
    from classify_festivals import classify
    from validate_prefecture_coordinates import apply_coordinate_prefectures
except ModuleNotFoundError:
    from scripts.classify_festivals import classify
    from scripts.validate_prefecture_coordinates import apply_coordinate_prefectures

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"active", "ended", "suspended", "unknown"}


def web_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def name_key(value):
    return re.sub(r"[\s・･「」『』（）()－—-]", "", unicodedata.normalize("NFKC", value)).casefold()


def validate(row, today=None):
    today = today or date.today()
    key = row.get("qid", "")
    if not re.fullmatch(r"(?:Q[1-9][0-9]*|local-[a-z0-9]+(?:-[a-z0-9]+)*)", key):
        raise ValueError(f"invalid stable key: {key}")
    for field in ("label_ja", "prefecture", "description", "description_source"):
        if not row.get(field):
            raise ValueError(f"{key}: missing {field}")
    venue = row.get("venue", {})
    if not venue.get("name") or not venue.get("coordinate_note"):
        raise ValueError(f"{key}: venue name and coordinate explanation required")
    if row["description_source"] != venue.get("source"):
        raise ValueError(f"{key}: description and venue must share reviewed source")
    for url in (row["description_source"], venue.get("coordinate_source")):
        if not web_url(url):
            raise ValueError(f"{key}: invalid source URL")
    if venue.get("precision") not in {"exact", "venue_area"}:
        raise ValueError(f"{key}: actual venue or venue area required")
    for field, low, high in (("latitude", 20, 46), ("longitude", 122, 154)):
        value = venue.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key}: invalid venue {field}")
        if row.get(field) != value:
            raise ValueError(f"{key}: marker must use the reviewed venue point")
    if "categories" in row:
        raise ValueError(f"{key}: categories are derived by classify_festivals, not hand-written")
    lifecycle = row.get("lifecycle", {})
    if lifecycle.get("status") not in STATUSES or not web_url(lifecycle.get("source")) or not lifecycle.get("evidence"):
        raise ValueError(f"{key}: lifecycle evidence required")
    checked = date.fromisoformat(lifecycle.get("checked_on", ""))
    if checked > today or (today - checked).days > 31:
        raise ValueError(f"{key}: batch review must be within the last 31 days")
    for occurrence in row.get("occurrences", []):
        start, end = date.fromisoformat(occurrence["start"]), date.fromisoformat(occurrence["end"])
        if start > end or start.year != occurrence["year"] or not web_url(occurrence.get("source")):
            raise ValueError(f"{key}: invalid verified occurrence")


def apply_batch(existing, batch, features, today=None):
    rows = deepcopy(existing)
    by_id = {row["qid"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("existing data has duplicate IDs")
    names = {}
    for row in rows:
        for name in [row.get("label_ja", ""), *row.get("aliases", [])]:
            names[(row.get("prefecture"), name_key(name))] = row["qid"]
    seen = set()
    for raw in batch:
        row = deepcopy(raw)
        validate(row, today)
        # Same vocabulary and rules as the full reclassification run.
        row["categories"] = classify(row)
        key = row["qid"]
        if key in seen:
            raise ValueError(f"duplicate batch ID: {key}")
        seen.add(key)
        apply_coordinate_prefectures([row], features)
        if row["coordinate_prefecture"] != row["prefecture"]:
            raise ValueError(f"{key}: venue lies outside declared prefecture")
        if key in by_id:
            # Re-running a batch may not overwrite later enrichment or unrelated data.
            if by_id[key] != row:
                raise ValueError(f"{key}: existing record differs; review explicitly")
            continue
        for name in [row["label_ja"], *row.get("aliases", [])]:
            signature = (row["prefecture"], name_key(name))
            if signature in names:
                raise ValueError(f"{key}: name already registered as {names[signature]}")
            names[signature] = key
        rows.append(row)
        by_id[key] = row
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "frontend/festivals.json")
    parser.add_argument("--batch", type=Path, default=ROOT / "data/official-festivals-20260929.json")
    parser.add_argument("--boundaries", type=Path, required=True, help="Downloaded pinned JapanPrefGeoJson boundary file")
    parser.add_argument("--limit", type=int, help="Review a pilot subset first")
    parser.add_argument("--apply", action="store_true", help="Without this flag only validate")
    args = parser.parse_args()
    existing = json.loads(args.data.read_text())
    batch = json.loads(args.batch.read_text())
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        batch = batch[:args.limit]
    features = json.loads(args.boundaries.read_text())["features"]
    rows = apply_batch(existing, batch, features)
    added = len(rows) - len(existing)
    if args.apply:
        temporary = args.data.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.data)
    print(f"validated={len(batch)} added={added} total={len(rows)} applied={args.apply}")


if __name__ == "__main__":
    main()
