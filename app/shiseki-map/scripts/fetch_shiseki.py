#!/usr/bin/env python3
"""出典と座標を持つ日本の史跡候補をWikidataから収集する。"""
import json
import math
import re
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "frontend" / "shiseki.json"
sys.path.insert(0, str(ROOT.parent / "omatsuri-map" / "scripts"))
from validate_prefecture_coordinates import containing_prefecture, fetch_features  # noqa:E402

ENDPOINT = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "ShisekiMap/1.0 (https://github.com/ats030/shiseki-map)"}
NATIONAL_SOURCE = "https://kunishitei.bunka.go.jp/bsys/index"

# 文化財指定 (P1435) のQID → designation。都道府県・市町村指定を地方指定(local)として含める。
DESIGNATION_QIDS = {
    "Q26764449": "special",   # 日本国指定特別史跡
    "Q30834580": "national",  # 日本国指定史跡
    "Q123010864": "local",    # 都道府県指定史跡
    "Q123010988": "local",    # 市町村指定史跡
}
DESIGNATION_PRIORITY = {"special": 3, "national": 2, "local": 1}
DESIGNATION_LABEL = {"special": "特別史跡", "national": "国指定史跡", "local": "地方指定史跡"}
DESIGNATION_VALUES = " ".join("wd:" + qid for qid in DESIGNATION_QIDS)

QUERY = r"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?article ?designation ?designationLabel ?eraLabel WHERE {
  ?item wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P1435 ?designation.
  VALUES ?designation { %s }
  OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://ja.wikipedia.org/>. }
  OPTIONAL { ?item wdt:P2348 ?era. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
""" % DESIGNATION_VALUES

# 広義の史跡・景観 (P31)。座標と日本語Wikipedia記事を持つものに限定。
BROAD_QUERY = r"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?article ?typeLabel ?eraLabel WHERE {
  VALUES ?type { wd:%s }
  ?item wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P31 ?type.
  ?article schema:about ?item; schema:isPartOf <https://ja.wikipedia.org/>.
  OPTIONAL { ?item wdt:P2348 ?era. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
# 遺跡・城・古墳・史跡 に加え、庭園・港・橋 を含める(用户指示「すべて含める」)。
BROAD_ROOTS = (
    "Q839954",   # 遺跡
    "Q23413",    # 城
    "Q109607",   # 古墳
    "Q1081138",  # 史跡
    "Q1107656",  # 庭園
    "Q283202",   # 港
    "Q12280",    # 橋
)


def point(value):
    lon, lat = value.removeprefix("Point(").removesuffix(")").split()
    return float(lat), float(lon)


def nearest_prefecture(lon, lat, features):
    """陸地のポリゴン外の海上座標に、最近傍の都道府県を返す(島間橋・離島など用)。

    各都道府県ポリゴンの外殻リングについて、座標がどの線分にも最も近い距離をkmで求める。
    経度は cos(mid_latitude) で補正して平面近似する。日本の全座標が125〜145度なので
    反子午線の折り返しは処理しない。
    """
    best_name, best_sq = None, None
    for feature in features:
        geometry = feature.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        polygons = coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
        for polygon in polygons:
            for ring in [polygon[0]]:
                for i in range(len(ring) - 1):
                    x1, y1 = ring[i][:2]
                    x2, y2 = ring[i + 1][:2]
                    xw = math.cos(math.radians((y1 + y2) / 2.0))
                    # xy plane: x=lon*xw, y=lat (deg, both ~111 km)
                    px, py = lon * xw, lat
                    ax, ay = x1 * xw, y1
                    bx, by = x2 * xw, y2
                    dx, dy = bx - ax, by - ay
                    if dx == 0 and dy == 0:
                        d2 = (px - ax) ** 2 + (py - ay) ** 2
                    else:
                        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
                        t = max(0.0, min(1.0, t))
                        cx, cy = ax + t * dx, ay + t * dy
                        d2 = (px - cx) ** 2 + (py - cy) ** 2
                    if best_sq is None or d2 < best_sq:
                        best_sq = d2
                        best_name = feature.get("properties", {}).get("nam_ja")
    return best_name


def category(types, label):
    text = "|".join(types) + "|" + label
    found = []
    rules = (("庭園", "庭園"), ("garden", "庭園"),
             ("港", "港"), ("harbor", "港"),
             ("橋", "橋"), ("bridge", "橋"),
             ("古墳", "古墳"),
             ("城", "城跡"), ("館跡", "城跡"),
             ("寺", "社寺・宗教遺跡"), ("神社", "社寺・宗教遺跡"),
             ("建築", "歴史的建造物"), ("遺跡", "遺跡"), ("史跡", "史跡"),
             ("ruin", "遺跡"), ("archaeological", "遺跡"), ("castle", "城跡"))
    lower = text.lower()
    for needle, value in rules:
        if needle.lower() in lower and value not in found:
            found.append(value)
    return found or ["その他"]


def highest_rank(ranks):
    if not ranks:
        return "undesig", "未指定"
    best = max(ranks, key=lambda r: DESIGNATION_PRIORITY[r])
    return best, DESIGNATION_LABEL[best]


def collect_designations():
    url = ENDPOINT
    params = {"query": QUERY, "format": "json"}
    response = requests.get(url, params=params, headers=HEADERS, timeout=180)
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def collect_broad():
    bindings = []
    for root in BROAD_ROOTS:
        response = requests.get(ENDPOINT, params={"query": BROAD_QUERY % root, "format": "json"},
                                headers=HEADERS, timeout=120)
        response.raise_for_status()
        bindings.extend(response.json()["results"]["bindings"])
        time.sleep(0.5)
    return bindings


def main():
    designations = collect_designations()
    broad = collect_broad()
    features = fetch_features()

    grouped = {}
    for binding in designations:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        rank = DESIGNATION_QIDS.get(binding["designation"]["value"].rsplit("/", 1)[-1])
        current = grouped.setdefault(qid, {"binding": binding, "ranks": [], "types": [], "eras": []})
        if rank and rank not in current["ranks"]:
            current["ranks"].append(rank)
        era = binding.get("eraLabel", {}).get("value", "")
        if era and era not in current["eras"]:
            current["eras"].append(era)
        current["binding"] = binding

    for binding in broad:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        current = grouped.setdefault(qid, {"binding": binding, "ranks": [], "types": [], "eras": []})
        current.setdefault("types", []).append(binding.get("typeLabel", {}).get("value", ""))
        era = binding.get("eraLabel", {}).get("value", "")
        if era and era not in current["eras"]:
            current["eras"].append(era)
        # 指定があるitem(国/地方)は広義のtypeのみ追加し、bindingは上書きしない
        if "ranks" not in current or not current["ranks"]:
            current["binding"] = binding

    rows = []
    for qid, group in grouped.items():
        binding = group["binding"]
        lat, lon = point(binding["coord"]["value"])
        rank, rank_label = highest_rank(group.get("ranks", []))
        article = binding.get("article", {}).get("value", "")
        title = requests.utils.unquote(article.rsplit("/", 1)[-1]).replace("_", " ") if article else ""
        label = binding["itemLabel"]["value"]
        if title and not re.search(r"[ぁ-んァ-ン一-龯]", label):
            label = title
        if rank in ("national", "special"):
            source = NATIONAL_SOURCE
        else:
            source = "https://www.wikidata.org/wiki/" + qid
        rows.append({
            "qid": qid, "label_ja": label, "label_en": "",
            "prefecture": containing_prefecture(lon, lat, features) or nearest_prefecture(lon, lat, features) or "",
            "latitude": lat, "longitude": lon,
            "description": binding.get("itemDescription", {}).get("value", ""),
            "title_ja": title or label,
            "categories": category(group.get("types", []), label),
            "era": "・".join(group.get("eras", [])),
            "designation": rank, "designation_label": rank_label,
            "designation_source": source,
            "heritage_id": "", "source_url": "https://www.wikidata.org/wiki/" + qid,
        })
    from merge_public_sites import merge_rows

    rows = merge_rows(rows)
    OUTPUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {}
    for item in rows:
        counts[item["designation"]] = counts.get(item["designation"], 0) + 1
    print(f"wrote {len(rows)} records to {OUTPUT}")
    print("designation breakdown:", dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
