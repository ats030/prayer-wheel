"""ja.wikipedia のインフォボックスの創建・竣工などの欄から時代を補う。

Wikidata に時代・創建年がない行だけを対象にする。値に伝承・下限・不確実さを示す語があるもの、
西暦年または時代名を含まないもの、複数の時代にまたがるものは採用しない。
"""
import json
import re
import time
from pathlib import Path

import requests

from gengo import gengo_spans

API = "https://ja.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "shiseki-map/1.0 (ats030@gmail.com)"}
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "wikipedia_cache" / "infobox_fields.json"
BATCH = 50

# 優先順。創建・築城など成立を表す欄を、竣工・開通など完成を表す欄より先に見る。
# build_y は日本の城郭概要表、建設は橋のインフォボックスの欄名。
FIELDS = ("創建", "創建年", "建立", "築城年", "build_y", "築造時期", "建設", "竣工", "完成", "開通", "時代")
REJECT_WORDS = ("伝", "以前", "以降", "?", "？", "不詳", "不明", "諸説", "説", "推定", "再建", "再興",
                "移転", "中興", "遷座", "再築", "改築", "頃", "ごろ", "年代", "未詳",
                "戦国",  # 戦国時代は室町時代と安土桃山時代にまたがる
                "初代")  # 架け替えられた橋では現存する橋の年と異なる
ERA_NAMES = ("飛鳥時代", "奈良時代", "平安時代", "鎌倉時代", "南北朝時代", "室町時代", "安土桃山時代",
             "江戸時代", "明治時代", "大正時代", "昭和時代", "平成時代", "令和時代")
# 南北朝は ERA_STARTS の区分では室町時代に含まれるため、年との照合用に揃える。
ERA_ALIASES = {"南北朝時代": "室町時代"}
# 改元が年の途中にある西暦年は、値に書かれた元号でどちらの時代か決める。
GENGO_BOUNDARIES = {1868: (("慶応", "江戸時代"), ("明治", "明治時代")),
                    1912: (("明治", "明治時代"), ("大正", "大正時代")),
                    1926: (("大正", "大正時代"), ("昭和", "昭和時代")),
                    1989: (("昭和", "昭和時代"), ("平成", "平成時代")),
                    2019: (("平成", "平成時代"), ("令和", "令和時代"))}


def clean_value(value):
    value = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>|<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"<[^>]+>|'''?", "", value)
    return value.strip()


def infobox_fields(wikitext):
    """対象欄の最初の値を {欄名: 値} で返す。"""
    fields = {}
    for name in FIELDS:
        match = re.search(r"^\s*\|\s*" + name + r"\s*=([^\n]*)", wikitext, flags=re.M)
        if match:
            value = clean_value(match.group(1))
            if value:
                fields[name] = value
    return fields


def gengo_year_era(gengo, year, era_of_year):
    """元号から求めた年の時代。改元の年は元号そのものでどちらの時代か決める。"""
    for name, era in GENGO_BOUNDARIES.get(year, ()):
        if name == gengo:
            return era
    return era_of_year(year)


def value_era(value, era_of_year):
    """欄の値から時代を1つに決められるときだけ返す。"""
    # 「永享年間か」のような推量も採用しない。
    if any(word in value for word in REJECT_WORDS) or re.search(r"年間?\s*か(?=$|[、。）)\s])", value):
        return None
    eras = set()
    for name in ERA_NAMES:
        if name in value:
            eras.add(ERA_ALIASES.get(name, name))
    for year in map(int, re.findall(r"(?<!\d)(\d{3,4})年", value)):
        if year in GENGO_BOUNDARIES:
            named = {era for gengo, era in GENGO_BOUNDARIES[year] if gengo in value}
            eras.update(named if len(named) == 1 else {None})
        else:
            eras.add(era_of_year(year))
    # 西暦のない「宝永2年」「天正年間」も元号の表で年に直す。年数が元号の期間を超える値は採用しない。
    for gengo, first, last in gengo_spans(value):
        for year in {first, last}:
            eras.add(gengo_year_era(gengo, year, era_of_year) if year else None)
    for century in re.findall(r"(?<!\d)(\d{1,2})世紀", value):
        first = (int(century) - 1) * 100 + 1
        eras.add(era_of_year(first))
        eras.add(era_of_year(first + 99))
    if len(eras) != 1 or None in eras:
        return None
    return eras.pop()


def fields_era(fields, era_of_year):
    """優先順で最初に値のある欄だけを使う。その欄で決まらなければ下位の欄へは進まない。"""
    for name in FIELDS:
        # 橋の建設欄には施工者名だけのことがあるため、年や時代を含まない値は欄がないものとみなす。
        if name == "建設" and name in fields and not re.search(r"\d|時代", fields[name]):
            continue
        if name in fields:
            era = value_era(fields[name], era_of_year)
            return (era, name) if era else None
    return None


def load_cache():
    """対象欄が前回と同じときだけキャッシュを使う。欄を足したら全記事を取り直す。"""
    if CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("fields") == list(FIELDS):
            return data["pages"]
    return {}


def fetch_batch(titles):
    """タイトルごとの対象欄を返す。本文を取得できなかったタイトルは含めない(次回再取得する)。"""
    params = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
              "titles": "|".join(titles), "redirects": 1, "format": "json", "formatversion": 2}
    result = {}
    alias = {}
    cont = {}
    while True:
        response = requests.post(API, data={**params, **cont}, headers=HEADERS, timeout=120)
        response.raise_for_status()
        data = response.json()
        query = data.get("query", {})
        for entry in query.get("normalized", []) + query.get("redirects", []):
            alias[entry["from"]] = entry["to"]
        for page in query.get("pages", []):
            if page.get("missing") or page.get("invalid"):
                result[page["title"]] = {}
            elif page.get("revisions"):
                result[page["title"]] = infobox_fields(page["revisions"][0]["slots"]["main"]["content"])
        if "continue" not in data:
            break
        cont = data["continue"]
    fields = {}
    for title in titles:
        target = title
        for _ in range(3):
            target = alias.get(target, target)
        if target in result:
            fields[title] = result[target]
    return fields


def collect_infobox_fields(titles):
    """タイトルごとの対象欄をキャッシュ付きで返す。"""
    cache = load_cache()
    pending = sorted({t for t in titles if t and t not in cache})
    for start in range(0, len(pending), BATCH):
        cache.update(fetch_batch(pending[start:start + BATCH]))
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"fields": list(FIELDS), "pages": cache}, ensure_ascii=False),
                              encoding="utf-8")
        time.sleep(0.2)
    if pending:
        print(f"fetched infobox fields for {len(pending)} titles")
    return {t: cache.get(t, {}) for t in titles}
