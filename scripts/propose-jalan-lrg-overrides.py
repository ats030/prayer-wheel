#!/usr/bin/env python3
"""Propose explicit LRG overrides for records unresolved by the base generator."""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = Path(__file__).with_name("generate-jalan-lrg.py")
spec = importlib.util.spec_from_file_location("jalan_lrg_generator", GENERATOR_PATH)
generator = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(generator)


def area_page(item):
    code, (prefecture, name) = item
    url = f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/"
    text = generator.fetch(url).decode("shift_jis", errors="ignore")
    municipalities = {
        prefecture + value
        for value in re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', text)
    }
    match = re.search(r'"yad_ids"\s*:\s*\[([^]]+)]', text)
    hotel_ids = re.findall(r'"(\d+)"', match.group(1))[:3] if match else []
    return code, name, municipalities, hotel_ids


def hotel_coordinate(hotel_id: str):
    text = generator.fetch(f"https://www.jalan.net/yad{hotel_id}/").decode("shift_jis", errors="ignore")
    match = re.search(r"staticmap\?center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    if not match:
        return hotel_id, None
    return hotel_id, (float(match.group(1)), float(match.group(2)))


def distance_km(lat1, lng1, lat2, lng2):
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/jalan-lrg-overrides.json")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    areas = generator.load_areas()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        area_rows = list(pool.map(area_page, areas.items()))

    hotel_to_area = {}
    municipality_areas = defaultdict(set)
    for code, _, municipalities, hotel_ids in area_rows:
        for municipality in municipalities:
            municipality_areas[municipality].add(code)
        for hotel_id in hotel_ids:
            hotel_to_area[hotel_id] = code

    area_points = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for hotel_id, point in pool.map(hotel_coordinate, hotel_to_area):
            if point:
                area_points[hotel_to_area[hotel_id]].append(point)

    boundaries = generator.load_boundaries(args.boundaries)
    overrides = json.loads(args.output.read_text()) if args.output.exists() else {}
    unresolved = []
    for dataset in generator.DATASETS:
        records = json.loads((ROOT / dataset).read_text())
        for record in records:
            if record.get("jalan_lrg_code"):
                qid = str(record.get("qid"))
                code = record["jalan_lrg_code"]
                existing = overrides.get(qid)
                if existing and existing["code"] != code:
                    raise SystemExit(f"conflicting assignments for {qid}: {existing['code']} vs {code}")
                if not existing:
                    overrides[qid] = {
                        "code": code,
                        "name": record["jalan_lrg_name"],
                        "evidence": {
                            "method": "existing_static_assignment",
                            "point_name": record.get("label_ja") or record.get("title_ja") or "",
                            "official_url": f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/",
                            "confirmed_at": date.today().isoformat(),
                        },
                    }
                continue
            prefecture = str(record.get("prefecture", ""))
            lat, lng = float(record["latitude"]), float(record["longitude"])
            municipality = generator.municipality_at(boundaries, prefecture, lat, lng)
            candidates = sorted(municipality_areas.get(municipality, ()))
            candidate_source = "municipality"
            if not candidates:
                candidates = sorted(code for code, value in areas.items() if value[0] == prefecture)
                candidate_source = "prefecture"
            distances = []
            for code in candidates:
                points = area_points.get(code, ())
                if points:
                    distances.append((min(distance_km(lat, lng, p[0], p[1]) for p in points), code))
            if not distances:
                unresolved.append({"dataset": str(dataset), "qid": record.get("qid"), "candidates": candidates})
                continue
            distances.sort()
            best_distance, code = distances[0]
            runner_up = distances[1][0] if len(distances) > 1 else None
            qid = str(record.get("qid"))
            existing = overrides.get(qid)
            if existing and existing["code"] != code:
                raise SystemExit(f"conflicting assignments for {qid}: {existing['code']} vs {code}")
            overrides[qid] = {
                "code": code,
                "name": areas[code][1],
                "evidence": {
                    "method": f"nearest_official_jalan_hotels_within_{candidate_source}",
                    "municipality": municipality,
                    "distance_km": round(best_distance, 3),
                    "runner_up_km": round(runner_up, 3) if runner_up is not None else None,
                    "point_name": record.get("label_ja") or record.get("title_ja") or "",
                    "official_url": f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/",
                    "confirmed_at": date.today().isoformat(),
                },
            }
    if unresolved:
        raise SystemExit(json.dumps({"unresolved": unresolved}, ensure_ascii=False, indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(overrides, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"overrides": len(overrides), "areas_with_points": len(area_points)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
