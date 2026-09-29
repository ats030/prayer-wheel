"""ja.wikipedia のインフォボックスの創建・竣工などの欄から時代を補う。

Wikidata に時代・創建年がない行だけを対象にする。値に伝承・下限・不確実さを示す語があるもの、
西暦年または時代名を含まないもの、複数の時代にまたがるものは採用しない。
"""
import json
import re
import time
from pathlib import Path

import requests

API = "https://ja.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "shiseki-map/1.0 (ats030@gmail.com)"}
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "wikipedia_cache" / "infobox_fields.json"
BATCH = 50

# 優先順。創建・築城など成立を表す欄を、竣工・開通など完成を表す欄より先に見る。
FIELDS = ("創建", "創建年", "建立", "築城年", "築造時期", "竣工", "完成", "開通", "時代")
REJECT_WORDS = ("伝", "以前", "以降", "?", "？", "不詳", "不明", "諸説", "説", "推定", "再建", "再興",
                "移転", "中興", "遷座", "再築", "改築", "頃", "ごろ", "年代",
                "戦国")  # 戦国時代は室町時代と安土桃山時代にまたがる
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


def value_era(value, era_of_year):
    """欄の値から時代を1つに決められるときだけ返す。"""
    if any(word in value for word in REJECT_WORDS):
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
        if name in fields:
            era = value_era(fields[name], era_of_year)
            return (era, name) if era else None
    return None


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
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
        CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.2)
    if pending:
        print(f"fetched infobox fields for {len(pending)} titles")
    return {t: cache.get(t, {}) for t in titles}
