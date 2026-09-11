#!/usr/bin/env python3
"""公式情報で確認した会場をライブデータへ反映する。"""

import argparse
import json
from pathlib import Path


VERIFIED_VENUES = {
    "Q132860355": {
        "name": "古ケ崎河川敷スポーツ広場",
        "latitude": 35.80247,
        "longitude": 139.89385,
        "source": "https://matsudo-hanabi.com/",
        "coordinate_source": "https://www.wikidata.org/wiki/Q132860355",
        "precision": "venue_area",
    },
}

VERIFIED_DESCRIPTIONS = {
    "Q132860355": "松戸花火大会は、千葉県松戸市の古ケ崎河川敷スポーツ広場で開催される花火大会です。2026年は12,000発の打上花火とスターマインが予定されています。",
}


def apply_venues(rows, verified=VERIFIED_VENUES, descriptions=VERIFIED_DESCRIPTIONS):
    found = set()
    for row in rows:
        qid = row.get("qid")
        if qid not in verified:
            continue
        venue = verified[qid]
        if not venue.get("source") or not venue.get("coordinate_source"):
            raise ValueError(f"venue sources are required: {qid}")
        found.add(qid)
        row["venue"] = dict(venue)
        if qid in descriptions:
            row["description"] = descriptions[qid]
            row["description_source"] = venue["source"]
    missing = set(verified) - found
    if missing:
        raise ValueError(f"QID not found: {', '.join(sorted(missing))}")
    return rows


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "frontend/festivals.json")
    args = parser.parse_args()
    rows = json.loads(args.data.read_text(encoding="utf-8"))
    write_json(args.data, apply_venues(rows))
    print(f"verified venues applied: {len(VERIFIED_VENUES)} festivals")


if __name__ == "__main__":
    main()
