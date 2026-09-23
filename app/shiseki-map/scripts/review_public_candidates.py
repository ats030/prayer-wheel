#!/usr/bin/env python3
"""Reproduce the 2026-09-23 record-level review from pinned public CSVs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from audit_public_supply import normalized_name, read_csv, valid_coordinates

TOKYO_SHA256 = "0ceefb11fc6a6adbf1414e7733be2754f0e6fd867bacec02db2fd1afe72a73ee"
OKINAWA_SHA256 = "25f57972a9fe70f75ed9d98d836b264edf6b1af3ac2d1cd7c3870cb7636b2460"
TOKYO_SOURCE = "https://catalog.data.metro.tokyo.lg.jp/dataset/t000021d0000000017"
OKINAWA_SOURCE = "https://data.bodik.jp/dataset/470007_bunkazai"

# Manually checked against the linked public authority pages on 2026-09-23.
# A publish decision concerns the site's existence and visitor access, not its old CSV hours.
TOKYO_CURRENT_EVIDENCE = {
    "0000000114": {
        "status": "publish",
        "url": "https://www.city.ota.tokyo.jp/shisetsu/park/tamagawadai.html",
        "finding": "Park includes the kofun group; CSV hours describe the exhibit room, not park access.",
        "visit_data_conflict": True,
    },
    "0000000115": {
        "status": "publish",
        "url": "https://www.setagayadigitalmuseum.jp/information/842/detail/",
        "finding": "The 2026 autumn ward guidance locates public visits at the kofun in Tamagawa Noge Park.",
        "visit_data_conflict": False,
    },
    "0000000116": {
        "status": "hold",
        "url": "https://www.setagayadigitalmuseum.jp/information/other/131495380/",
        "finding": "The next room-opening period is announced for autumn; daily entry cannot be inferred.",
        "visit_data_conflict": False,
    },
    "0000000243": {
        "status": "publish",
        "url": "https://t-navi.city.taito.lg.jp/spot/1062",
        "finding": "Ward tourism page confirms access but current open days differ from the CSV.",
        "visit_data_conflict": True,
    },
}

# Possible identity matches; never merge based on this table alone.
OKINAWA_ALIAS_CANDIDATES = {
    "首里城跡": "首里城",
    "円覚寺跡": "円覚寺",
    "末吉宮跡": "末吉宮",
    "弁之御嶽": "弁ヶ嶽",
    "那覇市山下町第一洞穴": "山下町第一洞穴遺跡",
}


def checked_rows(path: Path, expected_sha256: str) -> list[dict[str, str]]:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"snapshot SHA-256 mismatch: {path}: {actual}")
    return read_csv(path)


def distance_m(lat: float, lon: float, other: dict) -> int:
    lat_scale = 111_195
    lon_scale = lat_scale * math.cos(math.radians((lat + other["latitude"]) / 2))
    return round(math.hypot((lat - other["latitude"]) * lat_scale,
                            (lon - other["longitude"]) * lon_scale))


def review(tokyo: Path, okinawa: Path, existing_path: Path) -> dict:
    tokyo_rows = checked_rows(tokyo, TOKYO_SHA256)
    okinawa_rows = checked_rows(okinawa, OKINAWA_SHA256)
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    # Reconstruct the map baseline used for this historical review. The three
    # accepted Tokyo records were published later and must not exclude themselves.
    existing = [item for item in existing if not str(item.get("id", "")).startswith("tokyo:130001:")]
    names: dict[str, set[str]] = defaultdict(set)
    for item in existing:
        names[item["prefecture"]].add(normalized_name(item["label_ja"]))
    tokyo = [row for row in tokyo_rows if row["種類"] in {"史跡", "旧跡"}
             and valid_coordinates(row) and "?" not in row["名称"]
             and "�" not in row["名称"]
             and normalized_name(row["名称"]) not in names.get("東京都", set())]
    okinawa = [row for row in okinawa_rows if "史跡" in row["文化財分類"]
               and valid_coordinates(row)]
    if (len(tokyo), len(okinawa)) != (81, 10):
        raise ValueError(f"candidate count changed: {len(tokyo)}, {len(okinawa)}")

    reviewed = []
    for prefecture, rows, source in (("東京都", tokyo, TOKYO_SOURCE),
                                      ("沖縄県", okinawa, OKINAWA_SOURCE)):
        coordinates: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in rows:
            coordinates[(row["緯度"], row["経度"])].append(row["名称"])
        current = [item for item in existing if item["prefecture"] == prefecture]
        for row in rows:
            title = row["名称"].strip()
            lat, lon = float(row["緯度"]), float(row["経度"])
            exact = [item for item in current if normalized_name(item["label_ja"]) == normalized_name(title)]
            possible_alias = OKINAWA_ALIAS_CANDIDATES.get(title) if prefecture == "沖縄県" else None
            alias = [item for item in current if item["label_ja"] == possible_alias]
            nearby = sorted((distance_m(lat, lon, item), item["label_ja"]) for item in current)[:1]
            same_point = [name.strip() for name in coordinates[(row["緯度"], row["経度"])]
                          if name.strip() != title]
            evidence = TOKYO_CURRENT_EVIDENCE.get(row["NO"]) if prefecture == "東京都" else None
            reasons = []
            if prefecture == "東京都":
                if not evidence:
                    reasons.append("visit_information_last_checked_2019")
                elif evidence["status"] == "hold":
                    reasons.append("seasonal_access_unconfirmed")
                else:
                    reasons.append("current_official_access_confirmed")
                if same_point:
                    reasons.append("coordinate_shared_with_distinct_record")
            else:
                reasons.append("no_visit_information_in_source")
                reasons.append("source_id_provisional_for_snapshot")
                if exact:
                    reasons.append("same_name_as_existing_map")
                if alias:
                    reasons.append("possible_alias_of_existing_map")
                if same_point:
                    reasons.append("coordinate_shared_with_distinct_record")
            if prefecture == "東京都":
                source_id = f'tokyo:130001:{row["NO"]}'
            else:
                stable_fields = "|".join((row["市区町村名"], normalized_name(title), row["文化財分類"]))
                source_id = "okinawa:2025-05:" + hashlib.sha256(stable_fields.encode()).hexdigest()[:16]
            reviewed.append({
                "source_id": source_id,
                "name": title,
                "prefecture": prefecture,
                "municipality": row["市区町村名"] if prefecture == "沖縄県" else "",
                "category": row["種類"] if prefecture == "東京都" else row["文化財分類"],
                "address": row["住所"],
                "latitude": lat,
                "longitude": lon,
                "source_url": source,
                "source_access_days": row["利用可能曜日"],
                "source_last_confirmed": row.get("最終確認日", ""),
                "status": evidence["status"] if evidence else "hold",
                "reasons": reasons,
                "current_evidence_url": evidence["url"] if evidence else "",
                "current_evidence_finding": evidence["finding"] if evidence else "",
                "visit_data_conflict": evidence["visit_data_conflict"] if evidence else False,
                "same_coordinate_as": same_point,
                "existing_name_match": [item["label_ja"] for item in exact],
                "existing_alias_candidate": [item["label_ja"] for item in alias],
                "nearest_existing": {"name": nearby[0][1], "distance_m": nearby[0][0]} if nearby else None,
            })
    ids = [row["source_id"] for row in reviewed]
    if len(ids) != len(set(ids)):
        raise ValueError("provisional source ID collision")
    return {
        "reviewed_at": "2026-09-23",
        "snapshot_sha256": {"tokyo": TOKYO_SHA256, "okinawa": OKINAWA_SHA256},
        "counts": {
            "total": len(reviewed),
            "publish": sum(row["status"] == "publish" for row in reviewed),
            "hold": sum(row["status"] == "hold" for row in reviewed),
            "independently_checked": sum(bool(row["current_evidence_url"]) for row in reviewed),
            "confirmed_visit_data_conflicts": sum(row["visit_data_conflict"] for row in reviewed),
            "existing_exact_name": sum(bool(row["existing_name_match"]) for row in reviewed),
            "existing_alias_candidate": sum(bool(row["existing_alias_candidate"]) for row in reviewed),
            "coordinate_shared_records": sum(bool(row["same_coordinate_as"]) for row in reviewed),
        },
        "records": reviewed,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokyo", type=Path, required=True)
    parser.add_argument("--okinawa", type=Path, required=True)
    parser.add_argument("--existing", type=Path, default=root / "frontend" / "shiseki.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output in {args.tokyo.resolve(), args.okinawa.resolve(), args.existing.resolve()}:
        raise ValueError("output must not overwrite an input")
    result = review(args.tokyo, args.okinawa, args.existing)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
