#!/usr/bin/env python3
"""文化庁 国指定文化財等データベースの史跡・特別史跡をスナップショットへ統合する。

出典: https://kunishitei.bunka.go.jp/ (利用規約 https://kunishitei.bunka.go.jp/top/policy
「出典を記載の上、自由にご利用ください」)。CSVは data/bunka_cache に保存し、再実行時は再取得しない。
"""
import csv
import io
import json
import math
import re
import unicodedata
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "bunka_cache"
CSV_PATH = CACHE / "shiseki.csv"
META_PATH = CACHE / "meta.json"
BASE = "https://kunishitei.bunka.go.jp"
DETAIL_URL = BASE + "/heritage/detail/401/{}"
SOURCE_NAME = "文化庁 国指定文化財等データベース"
SOURCE_LICENSE = "文化庁 国指定文化財等データベース 利用規約"
P4275_QUERY = 'SELECT ?item ?id WHERE { ?item wdt:P4275 ?id. FILTER(STRSTARTS(?id, "401/")) }'
NEAR_METERS = 1000
DUPLICATE_METERS = 50
HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)"(?: autocomplete="off")? value="([^"]*)"')
TOKEN = re.compile(r'name="_csrfToken"[^>]*value="([^"]+)"')


def fetch_csv() -> str:
    """一覧検索のセッションとCSRFトークンを経由して史跡・特別史跡のCSVを取得する。"""
    session = requests.Session()
    session.headers["User-Agent"] = "ShisekiMap/1.0 (https://github.com/ats030/shiseki-map)"
    index = session.get(BASE + "/bsys/index", timeout=60)
    index.raise_for_status()
    listing = session.post(BASE + "/bsys/searchlist", timeout=120, data={
        "_method": "POST", "_csrfToken": TOKEN.search(index.text).group(1), "screen_id": "index",
        "page_no": "1", "register_sub_id": "401",
        "entry_kind1_401[0]": "史跡", "entry_kind1_401[3]": "特別史跡",
    })
    listing.raise_for_status()
    # CSV出力フォームの hidden 項目(検索条件・トークン)をそのまま送る
    start = listing.text.index('action="/utile/csv-list"')
    form = listing.text[start:listing.text.index("</form>", start)]
    response = session.post(BASE + "/utile/csv-list", timeout=120, data=HIDDEN.findall(form))
    response.raise_for_status()
    text = response.content.decode("utf-8-sig")
    if not text.lstrip('"').startswith("台帳ID"):
        raise ValueError("unexpected CSV response from kunishitei.bunka.go.jp")
    return text


def load_csv() -> list[dict]:
    if not CSV_PATH.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        CSV_PATH.write_text(fetch_csv(), encoding="utf-8")
        META_PATH.write_text(json.dumps({"fetched": date.today().isoformat(), "source": BASE + "/bsys/index"},
                                        ensure_ascii=False) + "\n", encoding="utf-8")
    return list(csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8"))))


def p4275_map(bindings: list[dict]) -> dict[str, list[str]]:
    """管理対象ID(ゼロ埋めなし) → Wikidata QID の一覧。"""
    result: dict[str, list[str]] = {}
    for binding in bindings:
        heritage = binding["id"]["value"].split("/", 1)[1]
        if heritage.isdigit():
            result.setdefault(str(int(heritage)), []).append(binding["item"]["value"].rsplit("/", 1)[-1])
    return result


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"\([^)]*\)", "", name)
    return re.sub(r"[\s・･]", "", name)


def designation_of(item: dict) -> str:
    return "special" if "特別史跡" in (item["種別1"], item["種別2"]) else "national"


def distance(lat1, lon1, lat2, lon2) -> float:
    delta_lat = (lat1 - lat2) * 111_195
    delta_lon = (lon1 - lon2) * 111_195 * math.cos(math.radians(lat1))
    return math.hypot(delta_lat, delta_lon)


def coordinates(item: dict):
    try:
        return float(item["緯度"]), float(item["経度"])
    except ValueError:
        return None


def find_match(item, label, rows_by_qid, rows, qids):
    point = coordinates(item)
    for qid in qids:
        row = rows_by_qid.get(qid)
        # P4275 は同一QIDに他県の同名史跡のIDが付いていることがあるため、県か距離で確かめる
        if row and (row["prefecture"] == item["都道府県"] or point and distance(
                point[0], point[1], float(row["latitude"]), float(row["longitude"])) <= NEAR_METERS):
            return row, "p4275"
    key = normalize(label)
    same_pref = [row for row in rows if row["prefecture"] == item["都道府県"]]
    for row in same_pref:
        if normalize(row["label_ja"]) == key:
            return row, "name"
    if point:
        near = []
        for row in same_pref:
            other = normalize(row["label_ja"])
            if len(other) >= 2 and (other in key or key in other):
                meters = distance(point[0], point[1], float(row["latitude"]), float(row["longitude"]))
                if meters <= NEAR_METERS:
                    near.append((meters, row))
        if near:
            return min(near, key=lambda pair: pair[0])[1], "near"
        close = [row for row in same_pref
                 if distance(point[0], point[1], float(row["latitude"]), float(row["longitude"])) < DUPLICATE_METERS
                 and similar(label, row["label_ja"])]
        if close:
            return close[0], "close"
    return None, "none"


# 名称の照合で無視する一般語。固有部分(地名・人名)が2字以上共通するかを見る。
GENERIC = re.compile(r"古墳群|遺跡群|古墳|遺跡|神社|境内|及び|および|ならびに|並びに|[跡址旧墓所城館寺廃塔窯宅氏邸群の]")
JAPANESE = re.compile(r"[ぁ-んァ-ン一-龯]")


def similar(label: str, other: str) -> bool:
    """50m以内の行を同一物件とみなすか。英語ラベルだけのWikidata行は同一とみなす。"""
    if not JAPANESE.search(other):
        return True
    other = re.sub(r"\s*[(（][^)）]*[)）]$", "", other)
    # 古墳群・遺跡群は構成要素の1基と、窯跡・墓所などは近くの社寺と統合しない
    if label.endswith("群") != other.endswith("群"):
        return False
    if re.search(r"(神社|寺|院)$", other) and not re.search(r"神社|寺|院", label):
        return False
    left = GENERIC.sub("", unicodedata.normalize("NFKC", label))
    right = GENERIC.sub("", unicodedata.normalize("NFKC", other))
    return any(left[i:i + 2] in right for i in range(len(left) - 1) if not re.search(r"[\s()・･]", left[i:i + 2]))


RANK = {"national": 1, "special": 2}


def merge_bunka(rows: list[dict], items: list[dict], p4275: dict[str, list[str]], category,
                locate=lambda lat, lon: "") -> tuple[list[dict], dict]:
    """照合した行へ指定情報を付け、未掲載の史跡を新規行として加える。

    locate(lat, lon) は都道府県欄が空の(複数県にまたがる)史跡の県を座標から求める。
    """
    from fetch_shiseki import DESIGNATION_LABEL

    rows_by_qid = {row["qid"]: row for row in rows if row.get("qid")}
    stats = {"p4275": 0, "name": 0, "near": 0, "close": 0, "added": 0, "added_qid": 0, "no_coordinates": 0, "shared": 0}
    claimed = set()
    added, duplicates, shared = [], [], []
    for item in items:
        point = coordinates(item)
        # 複数県にまたがる史跡は都道府県欄が空で、所在地に県名から書かれている
        address = item["都道府県"] + item["所在地"].strip()
        if not item["都道府県"].strip() and point:
            item = {**item, "都道府県": locate(*point)}
        heritage = str(int(item["管理対象ID"]))
        label = item["名称"].split("\n", 1)[0].strip()
        rank = designation_of(item)
        url = DETAIL_URL.format(heritage)
        qids = p4275.get(heritage, [])
        row, method = find_match(item, label, rows_by_qid, rows, qids)
        if row is not None:
            stats[method] += 1
            key = row.get("id") or row["qid"]
            if key in claimed:
                # 同じ行に複数の指定が対応する場合は上位の区分(特別史跡)を根拠にする
                stats["shared"] += 1
                shared.append((label, row["label_ja"]))
                if RANK[rank] <= RANK[row["designation"]]:
                    continue
            claimed.add(key)
            if not JAPANESE.search(row["label_ja"]):
                row["label_ja"] = row["title_ja"] = label
            row.update(designation=rank, designation_label=DESIGNATION_LABEL[rank],
                       designation_source=url, heritage_id="401/" + heritage)
            continue
        if point is None:
            stats["no_coordinates"] += 1
            continue
        qid = next((q for q in qids if q not in rows_by_qid), "")
        new = {
            "id": "" if qid else "bunka:401:" + heritage, "qid": qid,
            "label_ja": label, "label_en": "", "prefecture": item["都道府県"],
            "address": address,
            "latitude": point[0], "longitude": point[1],
            "description": "", "title_ja": label,
            "categories": category(["史跡"], label),
            "era": "", "era_source": "",
            "designation": rank, "designation_label": DESIGNATION_LABEL[rank],
            "designation_source": url, "heritage_id": "401/" + heritage, "source_url": url,
            "source_name": SOURCE_NAME, "source_license": SOURCE_LICENSE,
        }
        if not qid:
            del new["qid"]
        else:
            del new["id"]
            rows_by_qid[qid] = new
            stats["added_qid"] += 1
        for other in rows:
            if other["prefecture"] == new["prefecture"] and distance(
                    point[0], point[1], float(other["latitude"]), float(other["longitude"])) < DUPLICATE_METERS:
                duplicates.append((label, other["label_ja"]))
                break
        added.append(new)
        stats["added"] += 1
    stats["near_duplicates"] = len(duplicates)
    for label, other in shared:
        print(f"bunka: designation shares an existing record: {label} -> {other}")
    for label, other in duplicates:
        print(f"bunka: new row within {DUPLICATE_METERS}m of existing record: {label} / {other}")
    return rows + added, stats
