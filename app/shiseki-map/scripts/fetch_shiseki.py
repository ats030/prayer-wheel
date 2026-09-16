#!/usr/bin/env python3
"""出典と座標を持つ日本の史跡候補をWikidataから収集する。"""
import json
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
QUERY = r"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?article ?designation ?designationLabel ?eraLabel WHERE {
  ?item wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P1435 ?designation.
  VALUES ?designation { wd:Q30834580 wd:Q26764449 }
  OPTIONAL { ?article schema:about ?item; schema:isPartOf <https://ja.wikipedia.org/>. }
  OPTIONAL { ?item wdt:P2348 ?era. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
BROAD_QUERY = r"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?article ?typeLabel ?eraLabel WHERE {
  VALUES ?type { wd:%s }
  ?item wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P31 ?type.
  ?article schema:about ?item; schema:isPartOf <https://ja.wikipedia.org/>.
  OPTIONAL { ?item wdt:P2348 ?era. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
"""
BROAD_ROOTS = ("Q839954", "Q23413", "Q109607", "Q1081138")

def point(value):
    lon, lat = value.removeprefix("Point(").removesuffix(")").split()
    return float(lat), float(lon)

def category(types, label):
    text = "|".join(types) + "|" + label
    found = []
    rules = (("古墳", "古墳"), ("城", "城跡"), ("館跡", "城跡"),
             ("寺", "社寺・宗教遺跡"), ("神社", "社寺・宗教遺跡"),
             ("建築", "歴史的建造物"), ("遺跡", "遺跡"), ("史跡", "史跡"),
             ("ruin", "遺跡"), ("archaeological", "遺跡"), ("castle", "城跡"))
    lower = text.lower()
    for needle, value in rules:
        if needle.lower() in lower and value not in found:
            found.append(value)
    return found or ["その他"]

def designation(values):
    joined = "|".join(values)
    if "特別史跡" in joined or "Special Historic Site" in joined:
        return "special", "特別史跡"
    if "史跡" in joined or "Historic Site of Japan" in joined:
        return "national", "国指定史跡"
    if values:
        return "local", values[0]
    return "undesig", "未指定"

def main():
    response = requests.get(ENDPOINT, params={"query": QUERY, "format": "json"}, headers=HEADERS, timeout=180)
    response.raise_for_status()
    broad_bindings = []
    for root in BROAD_ROOTS:
        broad_response = requests.get(ENDPOINT, params={"query": BROAD_QUERY % root, "format": "json"}, headers=HEADERS, timeout=120)
        broad_response.raise_for_status()
        broad_bindings.extend(broad_response.json()["results"]["bindings"])
        time.sleep(0.5)
    features = fetch_features()
    grouped = {}
    for binding in response.json()["results"]["bindings"]:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        current = grouped.setdefault(qid, {"binding": binding, "designations": [], "eras": []})
        current["designations"].append(binding["designationLabel"]["value"])
        era = binding.get("eraLabel", {}).get("value", "")
        if era and era not in current["eras"]:
            current["eras"].append(era)
        if binding["designation"]["value"].endswith("Q26764449"):
            current["binding"] = binding
    for binding in broad_bindings:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        current = grouped.setdefault(qid, {"binding": binding, "designations": [], "types": [], "eras": []})
        current.setdefault("types", []).append(binding.get("typeLabel", {}).get("value", ""))
        era = binding.get("eraLabel", {}).get("value", "")
        if era and era not in current["eras"]:
            current["eras"].append(era)
    rows = []
    for qid, group in grouped.items():
        binding = group["binding"]
        lat, lon = point(binding["coord"]["value"])
        types = group.get("types", [])
        values = group["designations"]
        rank, rank_label = designation(values)
        article = binding.get("article", {}).get("value", "")
        title = requests.utils.unquote(article.rsplit("/", 1)[-1]).replace("_", " ") if article else ""
        label = binding["itemLabel"]["value"]
        if title and not re.search(r"[ぁ-んァ-ン一-龯]", label):
            label = title
        rows.append({
            "qid": qid, "label_ja": label, "label_en": "",
            "prefecture": containing_prefecture(lat, lon, features) or "",
            "latitude": lat, "longitude": lon,
            "description": binding.get("itemDescription", {}).get("value", ""),
            "title_ja": title or label,
            "categories": category(types, label), "era": "・".join(group.get("eras", [])),
            "designation": rank, "designation_label": rank_label,
            "designation_source": "https://kunishitei.bunka.go.jp/bsys/index",
            "heritage_id": "", "source_url": "https://www.wikidata.org/wiki/" + qid,
        })
    rows.sort(key=lambda item: (item["prefecture"], item["label_ja"]))
    OUTPUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} records to {OUTPUT}")

if __name__ == "__main__":
    main()
