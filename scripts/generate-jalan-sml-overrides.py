#!/usr/bin/env python3
"""Build point-to-Jalan-small-area assignments from official pages."""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = Path(__file__).with_name("generate-jalan-lrg.py")
spec = importlib.util.spec_from_file_location("jalan_generator", GENERATOR)
base = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(base)


def load_tree():
    root = ET.fromstring(base.fetch(base.AREA_XML))
    result = {}
    for pref in root.findall("Prefecture"):
        for large in pref.findall("LargeArea"):
            for small in large.findall("SmallArea"):
                result[small.attrib["cd"]] = {
                    "name": small.attrib["name"],
                    "lrg_code": large.attrib["cd"],
                    "lrg_name": large.attrib["name"],
                    "prefecture": pref.attrib["name"],
                }
    return result


def small_page(item):
    code, area = item
    url = f"https://www.jalan.net/{code[:2]}0000/LRG_{area['lrg_code']}/SML_{code}/"
    text = base.fetch(url).decode("shift_jis", errors="ignore")
    municipalities = {
        area["prefecture"] + value
        for value in re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', text)
    }
    match = re.search(r'"yad_ids"\s*:\s*\[([^]]+)]', text)
    hotels = re.findall(r'"(\d+)"', match.group(1))[:3] if match else []
    return code, municipalities, hotels


def hotel_point(hotel_id):
    text = base.fetch(f"https://www.jalan.net/yad{hotel_id}/").decode("shift_jis", errors="ignore")
    match = re.search(r"staticmap\?center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    return hotel_id, (float(match.group(1)), float(match.group(2))) if match else None


def distance(a, b):
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lng2-lng1)/2)**2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(1-value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output", type=Path, default=ROOT / "data/jalan-sml-overrides.json")
    args = parser.parse_args()
    areas = load_tree()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(small_page, areas.items()))
    municipality_areas = defaultdict(set)
    hotel_area = {}
    for code, municipalities, hotels in rows:
        for municipality in municipalities:
            municipality_areas[municipality].add(code)
        for hotel in hotels:
            hotel_area[hotel] = code
    points = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for hotel, point in pool.map(hotel_point, hotel_area):
            if point:
                points[hotel_area[hotel]].append(point)
    boundaries = base.load_boundaries(args.boundaries)
    result = {}
    for dataset in base.DATASETS:
        records = json.loads((ROOT / dataset).read_text())
        for record in records:
            qid = str(record["qid"])
            lrg = record["jalan_lrg_code"]
            latlng = (float(record["latitude"]), float(record["longitude"]))
            municipality = base.municipality_at(boundaries, record["prefecture"], *latlng)
            within_lrg = {code for code, area in areas.items() if area["lrg_code"] == lrg}
            candidates = sorted(municipality_areas.get(municipality, set()) & within_lrg)
            method = "official_small_area_municipality"
            if len(candidates) != 1:
                candidates = sorted(within_lrg)
                ranked = sorted(
                    (min(distance(latlng, point) for point in points[code]), code)
                    for code in candidates if points.get(code)
                )
                if not ranked:
                    raise SystemExit(f"no SML candidate evidence for {qid} in {lrg}")
                code = ranked[0][1]
                gap = round(ranked[1][0] - ranked[0][0], 3) if len(ranked) > 1 else None
                method = "nearest_official_jalan_hotels_within_lrg"
            else:
                code = candidates[0]
                gap = None
            area = areas[code]
            result[qid] = {
                "lrg_code": lrg,
                "lrg_name": record["jalan_lrg_name"],
                "sml_code": code,
                "sml_name": area["name"],
                "evidence": {
                    "method": method,
                    "municipality": municipality,
                    "runner_up_gap_km": gap,
                    "point_name": record.get("label_ja") or record.get("title_ja") or "",
                    "official_url": f"https://www.jalan.net/{code[:2]}0000/LRG_{lrg}/SML_{code}/",
                    "confirmed_at": date.today().isoformat(),
                },
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"records": len(result), "small_areas": len(areas)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
