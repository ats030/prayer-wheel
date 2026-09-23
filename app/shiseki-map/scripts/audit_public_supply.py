#!/usr/bin/env python3
"""Audit three downloaded public datasets without changing published data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from collections import Counter
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("cp932"))))


def normalized_name(value: str) -> str:
    return re.sub(r"[\s　・·ー（）()]+", "", value).casefold()


def valid_coordinates(row: dict[str, str]) -> bool:
    try:
        lat, lon = float(row["緯度"]), float(row["経度"])
    except (ValueError, KeyError):
        return False
    return 20 <= lat <= 46 and 122 <= lon <= 154


def names_in_map(path: Path) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for row in json.loads(path.read_text(encoding="utf-8")):
        names.setdefault(row["prefecture"], set()).add(normalized_name(row["label_ja"]))
    return names


def csv_metrics(path: Path, prefecture: str, site_rule, existing: dict[str, set[str]]) -> dict:
    rows = read_csv(path)
    names = existing.get(prefecture, set())
    candidates = [row for row in rows if site_rule(row)]
    located = [row for row in candidates if valid_coordinates(row)]
    keys = [(normalized_name(row["名称"]), row["緯度"], row["経度"]) for row in located]
    garbled = [row for row in located if "?" in row["名称"] or "�" in row["名称"]]
    screened = [
        row for row in located
        if row["名称"].strip() and row not in garbled
        and normalized_name(row["名称"]) not in names
        and row["利用可能曜日"].strip()
    ]
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "records": len(rows),
        "with_valid_japan_coordinates": sum(valid_coordinates(row) for row in rows),
        "site_class_candidates": len(candidates),
        "located_site_class_candidates": len(located),
        "missing_name_in_located_candidates": sum(not row["名称"].strip() for row in located),
        "garbled_name_in_located_candidates": len(garbled),
        "screened_new_candidates_with_access_days": len(screened),
        "exact_duplicate_rows_in_candidates": len(keys) - len(set(keys)),
        "same_name_as_existing_map": sum(normalized_name(row["名称"]) in names for row in located),
        "candidate_classes": dict(Counter(f'{row["文化財分類"]} / {row["種類"]}' for row in candidates).most_common()),
        "sample": [row["名称"] for row in located[::max(1, len(located) // 12)][:12]],
    }


def hokkaido_metrics(path: Path, existing: dict[str, set[str]]) -> dict:
    with zipfile.ZipFile(path) as archive:
        gpkg = next(name for name in archive.namelist() if name.endswith(".gpkg"))
        connection = sqlite3.connect(":memory:")
        connection.deserialize(archive.read(gpkg))
    try:
        tables = ("PointJGD2011", "PolygonJGD2011")
        features = [
            row
            for table in tables
            for row in connection.execute(f'SELECT "登載番�", "名称", "種別" FROM "{table}"')
        ]
        names = existing.get("北海道", set())
        ids = [row[0] for row in features if row[0]]
        # This is a geometry coverage check, not a visitability or positional accuracy check.
        geometry_counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}" WHERE geom IS NOT NULL').fetchone()[0]
            for table in tables
        }
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "point_features": sum(1 for _ in connection.execute('SELECT 1 FROM "PointJGD2011"')),
            "polygon_features": sum(1 for _ in connection.execute('SELECT 1 FROM "PolygonJGD2011"')),
            "features_with_geometry": geometry_counts,
            "features": len(features),
            "distinct_register_ids": len(set(ids)),
            "missing_register_id": len(features) - len(ids),
            "missing_name": sum(not (row[1] or "").strip() for row in features),
            "same_name_as_existing_map": sum(normalized_name(row[1] or "") in names for row in features),
            "site_types": dict(Counter(row[2] or "(empty)" for row in features).most_common(15)),
            "sample": [row[1] for row in features[::max(1, len(features) // 12)][:12]],
        }
    finally:
        connection.close()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokyo", type=Path, required=True)
    parser.add_argument("--okinawa", type=Path, required=True)
    parser.add_argument("--hokkaido", type=Path, required=True)
    parser.add_argument("--existing", type=Path, default=root / "frontend" / "shiseki.json")
    args = parser.parse_args()
    existing = names_in_map(args.existing)
    report = {
        "tokyo": csv_metrics(args.tokyo, "東京都", lambda row: row["種類"] in {"史跡", "旧跡"}, existing),
        "okinawa": csv_metrics(args.okinawa, "沖縄県", lambda row: "史跡" in row["文化財分類"], existing),
        "hokkaido": hokkaido_metrics(args.hokkaido, existing),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
