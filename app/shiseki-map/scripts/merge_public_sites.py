#!/usr/bin/env python3
"""Add individually verified public-source sites to the Wikidata snapshot."""

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPPLEMENT = ROOT / "data" / "verified_public_sites.json"
SNAPSHOT = ROOT / "frontend" / "shiseki.json"


def merge_rows(rows: list[dict]) -> list[dict]:
    additions = json.loads(SUPPLEMENT.read_text(encoding="utf-8"))
    if len(additions) != 4:
        raise ValueError("expected exactly four reviewed public-source records")
    addition_ids = {item["id"] for item in additions}
    if len(addition_ids) != len(additions):
        raise ValueError("duplicate source-scoped ID in supplement")
    base = [row for row in rows if (row.get("id") or row.get("qid")) not in addition_ids]
    existing_ids = {row.get("id") or row.get("qid") for row in base}
    for item in additions:
        if item["id"] in existing_ids or item.get("qid"):
            raise ValueError(f"source ID collision or unexpected Wikidata QID: {item['id']}")
        if not item["source_url"] or not item["visit_url"] or not item["access_note"]:
            raise ValueError(f"missing publication evidence: {item['id']}")
        for row in base:
            if row["prefecture"] != item["prefecture"]:
                continue
            if row["label_ja"].strip() == item["label_ja"].strip():
                raise ValueError(f"same-name map record: {item['label_ja']}")
            delta_lat = (float(row["latitude"]) - item["latitude"]) * 111_195
            delta_lon = (float(row["longitude"]) - item["longitude"]) * 111_195 * math.cos(math.radians(item["latitude"]))
            if math.hypot(delta_lat, delta_lon) < 50:
                raise ValueError(f"near-coincident map record: {item['label_ja']} / {row['label_ja']}")
    merged = base + additions
    merged.sort(key=lambda row: (row["prefecture"], row["label_ja"]))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    rows = json.loads(args.snapshot.read_text(encoding="utf-8"))
    merged = merge_rows(rows)
    args.snapshot.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(merged)} records to {args.snapshot}")


if __name__ == "__main__":
    main()
