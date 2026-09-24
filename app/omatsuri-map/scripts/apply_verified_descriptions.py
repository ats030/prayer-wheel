#!/usr/bin/env python3
"""公式ページで確認した説明・会場・開催期間をライブデータへ反映する。

確認済みデータは data/verified-descriptions.json に置く。説明文は出典ページに
書かれた事実だけで書き、会場と開催期間も同じ出典から取る。会場の座標は出典
ではなく geocoder の結果なので coordinate_source に別途記録する。
status が ended の祭りは最後の開催を occurrences に残し、説明文で終了を示す。
"""

import argparse
import json
from pathlib import Path

from apply_verified_occurrences import display_range


ROOT = Path(__file__).parents[1]
STATUSES = {"active", "ended"}


def validate(qid, entry):
    source = entry.get("source", "")
    if not source.startswith("https://") and not source.startswith("http://"):
        raise ValueError(f"source URL is required: {qid}")
    if entry.get("status") not in STATUSES:
        raise ValueError(f"unknown status: {qid}")
    if not entry.get("description"):
        raise ValueError(f"description is required: {qid}")
    venue = entry.get("venue") or {}
    if not venue.get("name"):
        raise ValueError(f"venue name is required: {qid}")
    has_point = "latitude" in venue and "longitude" in venue
    if has_point and not venue.get("coordinate_source"):
        raise ValueError(f"coordinate source is required: {qid}")
    if entry["status"] == "ended" and not entry.get("occurrences"):
        raise ValueError(f"ended festival needs its last occurrence: {qid}")


def apply_descriptions(rows, verified):
    found = set()
    for row in rows:
        qid = row.get("qid")
        if qid not in verified:
            continue
        entry = verified[qid]
        validate(qid, entry)
        found.add(qid)
        source = entry["source"]
        row["description"] = entry["description"]
        row["description_source"] = source
        venue = entry["venue"]
        # 座標がない会場も名前と住所は出典どおりに出す。地図の点は祭りの座標のまま。
        row["venue"] = {"name": venue["name"], "source": source}
        if venue.get("address"):
            row["venue"]["address"] = venue["address"]
        if "latitude" in venue:
            row["venue"].update({
                "latitude": venue["latitude"],
                "longitude": venue["longitude"],
                "coordinate_source": venue["coordinate_source"],
                "precision": venue.get("precision", "venue_area"),
            })
        if entry.get("occurrences"):
            by_key = {
                (item["year"], item["start"], item["end"]): item
                for item in row.get("occurrences", [])
            }
            for item in entry["occurrences"]:
                by_key[(item["year"], item["start"], item["end"])] = {**item, "source": source}
            occurrences = sorted(by_key.values(), key=lambda item: item["start"])
            row["occurrences"] = occurrences
            row["date"] = display_range(occurrences[-1])
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
    parser.add_argument("--data", type=Path, default=ROOT / "frontend/festivals.json")
    parser.add_argument("--verified", type=Path, default=ROOT / "data/verified-descriptions.json")
    args = parser.parse_args()
    verified = json.loads(args.verified.read_text(encoding="utf-8"))
    rows = json.loads(args.data.read_text(encoding="utf-8"))
    write_json(args.data, apply_descriptions(rows, verified))
    print(f"verified descriptions applied: {len(verified)} festivals")


if __name__ == "__main__":
    main()
