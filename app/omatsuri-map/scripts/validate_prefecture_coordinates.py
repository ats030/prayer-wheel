#!/usr/bin/env python3
"""都道府県境界で祭りの座標を検証し、実際の都道府県を付与する。"""

import argparse
import json
from pathlib import Path

import requests


BOUNDARY_REVISION = "13911412a4fb7ad6d52656edb8900a37b9e8e439"
BOUNDARY_URL = (
    "https://raw.githubusercontent.com/amay077/JapanPrefGeoJson/"
    f"{BOUNDARY_REVISION}/japan.geojson"
)


def point_in_ring(longitude, latitude, ring):
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > latitude) != (y2 > latitude):
            crossing = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < crossing:
                inside = not inside
        previous = current
    return inside


def point_in_polygon(longitude, latitude, polygon):
    return point_in_ring(longitude, latitude, polygon[0]) and not any(
        point_in_ring(longitude, latitude, hole) for hole in polygon[1:]
    )


def containing_prefecture(longitude, latitude, features):
    for feature in features:
        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
        if any(point_in_polygon(longitude, latitude, polygon) for polygon in polygons if polygon):
            return feature.get("properties", {}).get("nam_ja")
    return None


def apply_coordinate_prefectures(rows, features, source=BOUNDARY_URL):
    for row in rows:
        venue = row.get("venue") if isinstance(row.get("venue"), dict) else {}
        latitude = venue.get("latitude", row.get("latitude"))
        longitude = venue.get("longitude", row.get("longitude"))
        row["coordinate_prefecture"] = containing_prefecture(longitude, latitude, features)
        row["coordinate_validation_source"] = source
    return rows


def fetch_features():
    response = requests.get(BOUNDARY_URL, timeout=60)
    response.raise_for_status()
    return response.json()["features"]


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "frontend/festivals.json")
    args = parser.parse_args()
    rows = json.loads(args.data.read_text(encoding="utf-8"))
    write_json(args.data, apply_coordinate_prefectures(rows, fetch_features()))
    mismatches = sum(row.get("coordinate_prefecture") != row.get("prefecture") for row in rows)
    print(f"coordinate prefectures applied: {len(rows)} festivals; mismatches: {mismatches}")


if __name__ == "__main__":
    main()
