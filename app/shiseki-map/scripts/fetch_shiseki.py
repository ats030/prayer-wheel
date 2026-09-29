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
CACHE = ROOT / "data" / "wikidata_cache"
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
# 神社(Q845945)・仏教寺院(Q5393308)を「社寺・宗教遺跡」カテゴリへ集約する。
# 日本の城(Q92026)・古墳(Q1141225)は現行の上位QID(Q23413/Q109607)より件数が多いため併載する。
BROAD_ROOTS = (
    "Q839954",   # 遺跡
    "Q23413",    # 城
    "Q92026",    # 日本の城
    "Q109607",   # 古墳
    "Q1141225",  # 古墳(別)
    "Q1081138",  # 史跡
    "Q1107656",  # 庭園
    "Q283202",   # 港
    "Q12280",    # 橋
    "Q845945",   # 神社
    "Q5393308",  # 仏教寺院
    "Q908908",   # 陣屋
    "Q1152199",  # 貝塚
    "Q846760",   # 一里塚
    "Q4895508",  # 戦場
    "Q10856363", # 台場
    "Q994817",   # 本陣
)
# P31直下では取りこぼしが大きい種別は P279 サブクラスをたどる(宿場87→205件)。
BROAD_SUBCLASS_ROOTS = (
    "Q1209783",  # 宿場
    "Q3368243",  # 関所
)
BROAD_SUBCLASS_QUERY = BROAD_QUERY.replace("wdt:P31 ?type.", "wdt:P31/wdt:P279* ?type.")

# 登録有形文化財 (P1435)。「指定」ではなく「登録」なので designation は undesig のまま、
# designation_label で区別する。
REGISTERED_QID = "Q11579194"
REGISTERED_LABEL = "登録有形文化財"
REGISTERED_QUERY = r"""
SELECT DISTINCT ?item ?itemLabel ?itemDescription ?coord ?article ?eraLabel WHERE {
  ?item wdt:P17 wd:Q17; wdt:P625 ?coord; wdt:P1435 wd:%s.
  ?article schema:about ?item; schema:isPartOf <https://ja.wikipedia.org/>.
  OPTIONAL { ?item wdt:P2348 ?era. }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "ja,en". }
}
""" % REGISTERED_QID

# 地図に出さないQIDと理由。検証済み補足レコードと訪問点が重なるものに限る。
EXCLUDED_QIDS = {
    # 宿場町全体の項目だが座標は日野宿脇本陣跡(tokyo:130001:0000000136)と約24mで同一訪問点
    "Q11510578": "日野宿",
}


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
             ("建築", "歴史的建造物"), ("建造物", "歴史的建造物"), ("遺跡", "遺跡"), ("史跡", "史跡"),
             ("ruin", "遺跡"), ("archaeological", "遺跡"), ("castle", "城跡"),
             ("宿場", "史跡"), ("本陣", "史跡"), ("関所", "史跡"), ("一里塚", "史跡"),
             ("陣屋", "史跡"), ("台場", "史跡"), ("戦場", "史跡"), ("貝塚", "遺跡"))
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


def query_cached(key, query):
    """SPARQL結果をファイルキャッシュする。SPARQLは数十分かかるため、取得済み結果は再利用する。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE / (key + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    last_error = None
    for attempt in range(4):
        try:
            response = requests.get(ENDPOINT, params={"query": query, "format": "json"},
                                    headers=HEADERS, timeout=180)
            response.raise_for_status()
            rows = response.json()["results"]["bindings"]
            cache_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return rows
        except (requests.RequestException, ValueError) as error:
            last_error = error
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed to run query {key!r} after retries: {last_error}")


def collect_designations():
    return query_cached("designations", QUERY)


def collect_broad():
    bindings = []
    for root in BROAD_ROOTS:
        rows = query_cached("broad_" + root, BROAD_QUERY % root)
        print(f"using {len(rows)} rows for {root}")
        bindings.extend(rows)
        time.sleep(0.5)
    for root in BROAD_SUBCLASS_ROOTS:
        rows = query_cached("broad_sub_" + root, BROAD_SUBCLASS_QUERY % root)
        print(f"using {len(rows)} rows for {root} (with subclasses)")
        bindings.extend(rows)
        time.sleep(0.5)
    return bindings


def collect_registered():
    return query_cached("registered_" + REGISTERED_QID, REGISTERED_QUERY)


def main():
    designations = collect_designations()
    broad = collect_broad()
    registered = collect_registered()
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

    for binding in registered:
        qid = binding["item"]["value"].rsplit("/", 1)[-1]
        current = grouped.setdefault(qid, {"binding": binding, "ranks": [], "types": [], "eras": []})
        current["registered"] = True
        if "歴史的建造物" not in current["types"]:
            current["types"].append("歴史的建造物")
        era = binding.get("eraLabel", {}).get("value", "")
        if era and era not in current["eras"]:
            current["eras"].append(era)

    rows = []
    for qid, group in grouped.items():
        if qid in EXCLUDED_QIDS:
            continue
        binding = group["binding"]
        lat, lon = point(binding["coord"]["value"])
        rank, rank_label = highest_rank(group.get("ranks", []))
        if rank == "undesig" and group.get("registered"):
            rank_label = REGISTERED_LABEL
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
