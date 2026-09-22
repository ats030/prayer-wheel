#!/usr/bin/env python3
"""Add static Jalan large-area metadata to the three map datasets.

The generator combines the official Jalan area master and the municipalities
shown on each large-area results page with Geolonia's processed MLIT municipal
boundaries. The committed override table resolves ambiguous records, and the
command fails instead of silently emitting prefecture-level fallbacks.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


AREA_XML = "https://www.jalan.net/jalan/doc/jws/data/area.xml"
USER_AGENT = "ats030-map-lrg-generator/1.0"
DATASETS = (
    Path("app/onsen-map/frontend/onsen.json"),
    Path("app/omatsuri-map/frontend/festivals.json"),
    Path("app/shiseki-map/frontend/shiseki.json"),
)
OVERRIDES = Path("data/jalan-lrg-overrides.json")
SML_OVERRIDES = Path("data/jalan-sml-overrides.json")
PREF_CODE = {
    "北海道": "01", "青森県": "02", "岩手県": "03", "宮城県": "04", "秋田県": "05",
    "山形県": "06", "福島県": "07", "茨城県": "08", "栃木県": "09", "群馬県": "10",
    "埼玉県": "11", "千葉県": "12", "東京都": "13", "神奈川県": "14", "新潟県": "15",
    "富山県": "16", "石川県": "17", "福井県": "18", "山梨県": "19", "長野県": "20",
    "岐阜県": "21", "静岡県": "22", "愛知県": "23", "三重県": "24", "滋賀県": "25",
    "京都府": "26", "大阪府": "27", "兵庫県": "28", "奈良県": "29", "和歌山県": "30",
    "鳥取県": "31", "島根県": "32", "岡山県": "33", "広島県": "34", "山口県": "35",
    "徳島県": "36", "香川県": "37", "愛媛県": "38", "高知県": "39", "福岡県": "40",
    "佐賀県": "41", "長崎県": "42", "熊本県": "43", "大分県": "44", "宮崎県": "45",
    "鹿児島県": "46", "沖縄県": "47",
}


def fetch(url: str) -> bytes:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def load_areas() -> dict[str, tuple[str, str]]:
    root = ET.fromstring(fetch(AREA_XML))
    return {
        area.attrib["cd"]: (pref.attrib["name"], area.attrib["name"])
        for pref in root.findall("Prefecture")
        for area in pref.findall("LargeArea")
    }


def load_small_areas() -> dict[str, tuple[str, str, str, str]]:
    root = ET.fromstring(fetch(AREA_XML))
    return {
        small.attrib["cd"]: (pref.attrib["name"], large.attrib["cd"], large.attrib["name"], small.attrib["name"])
        for pref in root.findall("Prefecture")
        for large in pref.findall("LargeArea")
        for small in large.findall("SmallArea")
    }


def municipalities_for_area(item: tuple[str, tuple[str, str]]) -> tuple[str, set[str]]:
    code, (prefecture, _) = item
    url = f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/"
    text = fetch(url).decode("shift_jis", errors="ignore")
    localities = set(re.findall(r'"addressLocality"\s*:\s*"([^"]+)"', text))
    return code, {prefecture + locality for locality in localities}


def area_municipalities(areas: dict[str, tuple[str, str]], workers: int) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for code, municipalities in pool.map(municipalities_for_area, areas.items()):
            result[code] = municipalities
    return result


def bbox(geometry: dict) -> tuple[float, float, float, float]:
    coordinates = geometry["coordinates"]
    points = []
    stack = [coordinates]
    while stack:
        value = stack.pop()
        if value and isinstance(value[0], (int, float)):
            points.append(value)
        else:
            stack.extend(value)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def in_ring(lng: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > lat) != (y2 > lat):
            crossing = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lng < crossing:
                inside = not inside
        previous = current
    return inside


def in_polygon(lng: float, lat: float, polygon: list) -> bool:
    return in_ring(lng, lat, polygon[0]) and not any(
        in_ring(lng, lat, hole) for hole in polygon[1:]
    )


def contains(geometry: dict, lng: float, lat: float) -> bool:
    polygons = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        polygons = [polygons]
    return any(in_polygon(lng, lat, polygon) for polygon in polygons)


def load_boundaries(root: Path) -> dict[str, list[tuple[str, tuple, dict]]]:
    result: dict[str, list[tuple[str, tuple, dict]]] = defaultdict(list)
    for path in root.glob("[0-9][0-9]/[0-9]*.json"):
        data = json.loads(path.read_text())
        for feature in data["features"]:
            name = feature["properties"]["name"]
            geometry = feature["geometry"]
            result[path.parent.name].append((name, bbox(geometry), geometry))
    return result


def municipality_at(boundaries: dict, prefecture: str, lat: float, lng: float) -> str:
    pref_code = PREF_CODE.get(prefecture)
    if not pref_code:
        return ""
    for name, bounds, geometry in boundaries.get(pref_code, []):
        min_lng, min_lat, max_lng, max_lat = bounds
        if min_lng <= lng <= max_lng and min_lat <= lat <= max_lat and contains(geometry, lng, lat):
            return name
    return ""


def choose_area(candidates: list[str], areas: dict, label: str) -> str:
    if len(candidates) == 1:
        return candidates[0]
    normalized = re.sub(r"[温泉祭まつり城跡址史公園神社寺]", "", label)
    matches = [
        code for code in candidates
        if any(part and part in normalized for part in re.split(r"[・（）()]", areas[code][1]))
    ]
    return matches[0] if len(matches) == 1 else ""


def update_dataset(path: Path, boundaries: dict, areas: dict, municipality_areas: dict, overrides: dict,
                   small_areas: dict, sml_overrides: dict) -> dict:
    records = json.loads(path.read_text())
    reverse: dict[str, list[str]] = defaultdict(list)
    for code, municipalities in municipality_areas.items():
        for municipality in municipalities:
            reverse[municipality].append(code)

    assigned = 0
    for record in records:
        record.pop("jalan_lrg_code", None)
        record.pop("jalan_lrg_name", None)
        record.pop("jalan_sml_code", None)
        record.pop("jalan_sml_name", None)
        override = overrides.get(str(record.get("qid")))
        if override:
            code = override["code"]
            if code not in areas or override.get("name") != areas[code][1]:
                raise SystemExit(f"invalid override for {record.get('qid')}: {override}")
            if areas[code][0] != record.get("prefecture"):
                raise SystemExit(f"override prefecture mismatch for {record.get('qid')}: {override}")
            record["jalan_lrg_code"] = code
            record["jalan_lrg_name"] = areas[code][1]
            sml = sml_overrides.get(str(record.get("qid")))
            if not sml or sml.get("lrg_code") != code:
                raise SystemExit(f"missing or mismatched SML override for {record.get('qid')}")
            sml_code = sml.get("sml_code")
            expected = small_areas.get(sml_code)
            if not expected or expected != (record.get("prefecture"), code, areas[code][1], sml.get("sml_name")):
                raise SystemExit(f"invalid SML override for {record.get('qid')}: {sml}")
            record["jalan_sml_code"] = sml_code
            record["jalan_sml_name"] = expected[3]
            assigned += 1
            continue
        municipality = municipality_at(
            boundaries,
            str(record.get("prefecture", "")),
            float(record.get("latitude", 0)),
            float(record.get("longitude", 0)),
        )
        code = choose_area(
            reverse.get(municipality, []),
            areas,
            str(record.get("label_ja") or record.get("title_ja") or ""),
        )
        if code:
            record["jalan_lrg_code"] = code
            record["jalan_lrg_name"] = areas[code][1]
            assigned += 1
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    return {"path": str(path), "total": len(records), "assigned": assigned, "fallback": len(records) - assigned}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boundaries", type=Path, required=True, help="japanese-admins docs directory")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    areas = load_areas()
    small_areas = load_small_areas()
    municipality_areas = area_municipalities(areas, args.workers)
    boundaries = load_boundaries(args.boundaries)
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    sml_overrides = json.loads(SML_OVERRIDES.read_text()) if SML_OVERRIDES.exists() else {}
    report = [update_dataset(path, boundaries, areas, municipality_areas, overrides, small_areas, sml_overrides) for path in DATASETS]
    missing = sum(item["fallback"] for item in report)
    if missing:
        raise SystemExit(json.dumps({"error": "unassigned Jalan LRG records", "report": report}, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
