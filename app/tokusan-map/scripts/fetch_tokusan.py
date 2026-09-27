#!/usr/bin/env python3
"""日本各地の特産物 (食材・料理) を Wikidata + jawiki + LLM + Nominatim から
収集し、frontend/tokusan.json と data/place_cache.json を生成する。

手順:
  1. SPARQL で P31 が Q2095 (food) の直系/子孫 かつ P17 = Q17 (日本) の品目を取得
  2. 各項目から jawiki 記事本文 (exchars=1200) を取得
  3. ローカル Ollama で発祥地・産地抽出 -> {place, confidence, evidence}
  4. confidence >= 0.5 の件を Nominatim でジオコード
  5. 都道府県境界 GeoJSON で点包含検証 (一致しない場合は Nominatim の address に
     都道府県が含まれていなければ prefecture = "")

結果は data/place_cache.json (key = sha256(qid|label|text)) にキャッシュし、
既存の qid は再抽出しない。初回は Ollama による約160件の抽出に 15〜50分かかる。

使い方:
  python3 scripts/fetch_tokusan.py            # 未抽出分のみ追加
  python3 scripts/fetch_tokusan.py --recache  # キャッシュを無視して全件再抽出
  python3 scripts/fetch_tokusan.py --limit 10 # 先頭10件のみ
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "omatsuri-map" / "scripts"))
from validate_prefecture_coordinates import (  # noqa: E402
    containing_prefecture,
    fetch_features,
)

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
JAWIKI_API = "https://ja.wikipedia.org/w/api.php"
NOMS = "https://nominatim.openstreetmap.org/search"
OLLAMA = "http://localhost:11434/api/chat"
MODEL = "gemma4:12b"
CACHE = ROOT / "data" / "place_cache.json"
OUT = ROOT / "frontend" / "tokusan.json"
MIN_CONFIDENCE = 0.5
HEADERS = {"User-Agent": "TokusanMap/1.0 (https://github.com/ats030/tokusan-map)"}

SPARQL = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?item WHERE {
  ?item wdt:P31 ?t .
  { ?t wdt:P279* wd:Q2095 } UNION
  { ?t wdt:P279* wd:Q13464614 } UNION
  { ?t wdt:P279* wd:Q28823 } UNION
  { ?t wdt:P279* wd:Q368972 } .
  ?item wdt:P17 wd:Q17 .
}
LIMIT 500
"""

# LLM が選択するカテゴリ (code -> 表示名)。
# 食品 8 + 工芸 3 = 11 分類。工芸は Q13464614 (陶芸品) / Q28823 (織物) / Q368972 (漆器)。
CATEGORIES = [
    ("sa",  "酒・醸造"),
    ("te",  "茶・飲料"),
    ("ui",  "魚介"),
    ("sa2", "農産"),
    ("am",  "砂糖・和菓子"),
    ("ko",  "穀物・調味料"),
    ("ry",  "料理・惣菜"),
    ("ta",  "陶磁器"),
    ("or",  "織物"),
    ("ri",  "漆器"),
]
CATEGORY_CODES = [c for c, _ in CATEGORIES]
CATEGORY_PROMPT_CODES = "、".join(f"{c} ({name})" for c, name in CATEGORIES)

WIKIDATA_LABELS_API = "https://www.wikidata.org/w/api.php"

PROMPT = """あなたは日本の食文化の編集者です。
下の「日本の{label}」の記事本文を読んで、発祥地または代表的な産地 (地方) を1つ選んでください。

判定基準:
- 「〜発祥」「〜地方発祥」「〜県発祥」「〜名物」「郷土料理」などの記述を優先する
- 「全国に普及している」「全国各地で見られる」のみで、具体的な地方名の記述がない場合は
  place = "" とする
- 地方名は「〇〇県」「〇〇県〇〇市」などの日本語表記で書け (例: "長崎県", "熊本県川棚町")
- 曖昧な場合は confidence を0.3未満にする
- 日本語の回答で、JSONのみを出力すること (説明や改行は不要)

{"place": "〇〇県", "confidence": 0.9, "evidence": "記事文中の根拠となった30文字以内の引用"}

品目名: {label}
記事本文:
{text}
"""


def fetch_labels(qids):
    """wikidata API で ja/en ラベルと jawiki 記事名を取得して {qid: (ja, en, title)} を返す."""
    labels = {}
    for i in range(0, len(qids), 50):
        chunk = qids[i:i + 50]
        for attempt in range(3):
            try:
                resp = requests.get(WIKIDATA_LABELS_API, headers=HEADERS, params={
                    "action": "wbgetentities", "format": "json",
                    "ids": "|".join(chunk), "languages": "ja|en", "props": "labels|sitelinks", "sitefilter": "jawiki",
                }, timeout=60)
                resp.raise_for_status()
                for qid, ent in resp.json().get("entities", {}).items():
                    lab = ent.get("labels", {})
                    labels[qid] = (
                        lab.get("ja", {}).get("value", ""),
                        lab.get("en", {}).get("value", ""),
                        ent.get("sitelinks", {}).get("jawiki", {}).get("title", ""),
                    )
                break
            except requests.RequestException:
                time.sleep(1 + attempt)
    return labels


def sparql_fetch():
    """品目の (qid, label_ja, label_en) を取得する."""
    url = f"{SPARQL_ENDPOINT}?query={quote(SPARQL)}"
    last_err = None
    rows = None
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=HEADERS, params={"format": "json"}, timeout=180)
            resp.raise_for_status()
            rows = resp.json()["results"]["bindings"]
            break
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            time.sleep(5 + 10 * attempt)
    if rows is None:
        raise RuntimeError(f"SPARQL fetch failed: {last_err}")
    items = []
    seen = set()
    for r in rows:
        qid = r["item"]["value"].rsplit("/", 1)[-1]
        if not re.fullmatch(r"Q\d+", qid) or qid in seen:
            continue
        seen.add(qid)
        items.append(qid)

    labels = fetch_labels(items)
    items = [{
        "qid": qid,
        "label_ja": labels.get(qid, ("", "", ""))[0],
        "label_en": labels.get(qid, ("", "", ""))[1],
        "wiki_title": labels.get(qid, ("", "", ""))[2],
    } for qid in items]
    items.sort(key=lambda x: (x["label_ja"] or x["label_en"] or x["qid"], x["qid"]))
    return items


def jawiki_extract(title, exchars=1200):
    """jawiki 記事本文 (exchars文字) を取得する。失敗時は空文字列."""
    if not title:
        return ""
    for attempt in range(3):
        try:
            resp = requests.get(JAWIKI_API, headers=HEADERS, params={
                "action": "query", "format": "json", "prop": "extracts",
                "exintro": 1, "explaintext": 1, "exchars": exchars,
                "redirects": 1, "titles": title,
            }, timeout=30)
            resp.raise_for_status()
            pages = resp.json()["query"]["pages"]
            page = next(iter(pages.values()))
            return page.get("extract", "").strip()
        except (requests.RequestException, KeyError, StopIteration):
            time.sleep(1 + attempt)
    return ""


def ask_llm(label, text):
    text = text.strip()
    if len(text) > 4000:
        text = "".join(list(text)[:4000])
    payload = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT.replace("{label}", label).replace("{text}", text)}],
    }
    last_err = None
    for attempt in range(5):
        try:
            resp = requests.post(OLLAMA, json=payload, timeout=120, headers=HEADERS)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise ValueError(f"no JSON in LLM reply: {content[:200]}")
            obj = json.loads(content[start:end + 1])
            place = str(obj.get("place") or "").strip()
            try:
                confidence = float(obj.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            evidence = " ".join(str(obj.get("evidence") or "").split())[:160]
            place = re.sub(r"\s+", "", place)
            # 「東京都世田谷区県」のような誤った「県」を取り除き、都道府県名が無いときだけ補う
            place = re.sub(r"(?<=[市区町村])県$", "", place)
            if place and not re.search(r"[都道府県]", place):
                place += "県"
            return {"place": place, "confidence": confidence, "evidence": evidence}
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"LLM failed after retries: {last_err}")


CATEGORY_PROMPT = """あなたは日本の特産品分類の編集者です。
下の品目名を、必ず以下カテゴリのいずれか 1 つに分類してください。

カテゴリ (code と表示名):
{codes}

ルール:
- 品目名から類推して最も近い code を 1 つ選ぶ
- 判断に迷う場合は食品は ry (料理・惣菜)、工芸は品目名に合うものに寄せる
- 必ず {valid_codes} のいずれかを使う
- 各品目の code を、JSON 配列として品目名の順に出力する (説明や改行は不要)

例: ["sa", "ry", "ta"]

品目名:
{labels}
"""

CATEGORY_CACHE = ROOT / "data" / "category_cache.json"
CATEGORY_BATCH = 40


def load_category_cache():
    if CATEGORY_CACHE.exists():
        try:
            return json.loads(CATEGORY_CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_category_cache(cache):
    CATEGORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CATEGORY_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def classify_categories(labels):
    """品目名 (ラベル) からカテゴリ code を LLM でバッチ分類し {label: code} を返す。
    既にキャッシュ済みの label は再呼び出ししない。失敗した label は "" を代入する."""
    cache = load_category_cache()
    # 正規化: 連続空白を除去したものでキーを作る
    def norm(s):
        return re.sub(r"\s+", " ", (s or "").strip())

    uncached = [lab for lab in labels if lab and norm(lab) not in cache]
    if not uncached:
        return {lab: cache.get(norm(lab), "") for lab in labels}

    valid_codes = "、".join(CATEGORY_CODES)
    for i in range(0, len(uncached), CATEGORY_BATCH):
        batch = uncached[i:i + CATEGORY_BATCH]
        prompt = (CATEGORY_PROMPT
                  .replace("{codes}", CATEGORY_PROMPT_CODES)
                  .replace("{valid_codes}", valid_codes)
                  .replace("{labels}", "\n".join(f"{j}. {lab}" for j, lab in enumerate(batch, 1))))
        payload = {
            "model": MODEL,
            "stream": False,
            "think": False,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        codes = None
        last_err = None
        for attempt in range(5):
            try:
                resp = requests.post(OLLAMA, json=payload, timeout=120, headers=HEADERS)
                resp.raise_for_status()
                content = resp.json()["message"]["content"].strip()
                start = content.find("[")
                end = content.rfind("]")
                if start == -1 or end == -1:
                    raise ValueError(f"no JSON array in reply: {content[:200]}")
                arr = json.loads(content[start:end + 1])
                if not isinstance(arr, list) or len(arr) != len(batch):
                    raise ValueError(f"expected {len(batch)} codes, got {len(arr) if isinstance(arr, list) else type(arr)}")
                codes = [str(c).strip().lower() for c in arr]
                break
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                last_err = exc
                time.sleep(1 + attempt)
        # 失敗分は "" で埋める。成功分は検証してキャッシュへ
        for lab, code in zip(batch, codes or [""] * len(batch)):
            if code in CATEGORY_CODES:
                cache[norm(lab)] = code
            else:
                cache[norm(lab)] = ""
        save_category_cache(cache)

    return {lab: cache.get(norm(lab), "") for lab in labels}


def geocode(place):
    """Nominatim で座標 (lat, lon, address) を取得する。失敗時は None."""
    for attempt in range(3):
        try:
            resp = requests.get(NOMS, headers=HEADERS, params={
                "q": place, "countrycodes": "jp", "format": "json",
                "limit": 1,
            }, timeout=30)
            resp.raise_for_status()
            results = resp.json()
            if results:
                r = results[0]
                address = r.get("address", {})
                pref = address.get("state") or address.get("state_district") or ""
                city = address.get("city") or address.get("town") or address.get("village") or ""
                return (
                    float(r["lat"]), float(r["lon"]),
                    pref, city,
                )
            return None
        except (requests.RequestException, ValueError, KeyError):
            time.sleep(1 + attempt)
    return None


def make_key(qid, label, text):
    blob = f"{qid}|{label}|{text[:4000]}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_cache():
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def process_row(item, cache, prefecture_features):
    """既存のキャッシュがあればそれを返す。無ければ LLM -> Nominatim で追加抽出する."""
    label_ja = item["label_ja"] or item["label_en"] or item["qid"]
    # ラベル名で記事を引くと同名の別記事に当たるため、sitelink の記事名だけを使う
    wiki_title = item.get("wiki_title", "")
    text = jawiki_extract(wiki_title) if wiki_title else ""
    key = make_key(item["qid"], label_ja, text)

    if key in cache:
        entry = cache[key]
    elif not text:
        entry = {"place": "", "confidence": 0.0, "evidence": ""}
        cache[key] = entry
    else:
        entry = ask_llm(label_ja, text)
        cache[key] = entry

    place = entry.get("place", "")
    confidence = float(entry.get("confidence") or 0)
    evidence = entry.get("evidence", "")

    row = {
        "qid": item["qid"],
        "label_ja": item["label_ja"],
        "label_en": item["label_en"],
        "place": place,
        "confidence": confidence,
        "evidence": evidence,
        "category": "",
        "lat": 0.0, "lng": 0.0,
        "prefecture": "",
        "city": "",
        "wiki_title": wiki_title,
        "source_url": (f"https://ja.wikipedia.org/wiki/{quote(wiki_title.replace(' ', '_'))}"
                       if wiki_title else ""),
    }
    if not place or confidence < MIN_CONFIDENCE:
        return row

    geocoded = geocode(place)
    time.sleep(1.2)  # Nominatim の利用規約: リクエスト間 1秒以上
    if not geocoded:
        return row
    lat, lon, pref_from_osm, city = geocoded
    row["lat"], row["lng"], row["city"] = lat, lon, city

    # 点包含テスト
    contained = containing_prefecture(lon, lat, prefecture_features)
    if contained:
        row["prefecture"] = contained
    elif pref_from_osm:
        row["prefecture"] = pref_from_osm
    else:
        row["prefecture"] = ""

    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--recache", action="store_true")
    args = parser.parse_args()

    print("SPARQL 取得中...")
    items = sparql_fetch()
    if args.limit:
        items = items[:args.limit]
    print(f"取得品目: {len(items)}")

    if args.recache:
        cache = {}
    else:
        cache = load_cache()

    # GeoJSON を一度だけ取得
    print("都道府県境界 GeoJSON を取得中...")
    prefecture_features = None
    last_err = None
    for attempt in range(3):
        try:
            prefecture_features = fetch_features()
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(5 * (attempt + 1))
    if prefecture_features is None:
        print("警告: 境界 GeoJSON を取得できず、点包含検証をスキップします。")
        prefecture_features = []
    print(f"境界要素: {len(prefecture_features)} 件")

    processed = []
    for i, item in enumerate(items, 1):
        try:
            row = process_row(item, cache, prefecture_features)
            processed.append(row)
            print(f"[{i}/{len(items)}] {row['qid']} {row['label_ja']!r} -> "
                  f"place={row['place']!r} conf={row['confidence']} "
                  f"pref={row['prefecture']!r}")
            if i % 5 == 0:
                save_cache(cache)
        except RuntimeError as exc:
            print(f"[{i}/{len(items)}] {item['qid']} {item['label_ja']!r} ERROR: {exc}")

    save_cache(cache)

    print("カテゴリ分類中 (LLM バッチ)...")
    labels = [r.get("label_ja") or r.get("label_en") or r["qid"] for r in processed]
    category_map = classify_categories(labels)
    for r in processed:
        key = r.get("label_ja") or r.get("label_en") or r["qid"]
        r["category"] = category_map.get(key, "")
    cat_counts = {}
    for r in processed:
        cat_counts[r["category"] or "(未分類)"] = cat_counts.get(r["category"] or "(未分類)", 0) + 1
    print("カテゴリ内訳: " + ", ".join(f"{k}={v}" for k, v in sorted(cat_counts.items())))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(processed, ensure_ascii=False, indent=1), encoding="utf-8")

    with_place = [r for r in processed if r["place"]]
    with_location = [r for r in processed if r["lat"] or r["lng"]]
    with_pref = [r for r in processed if r["prefecture"]]
    print(f"\n完了: 品目 {len(processed)} 件 / 産地 {len(with_place)} / "
          f"座標 {len(with_location)} / 都道府県 {len(with_pref)}")
    print(f"出力: {OUT}")


if __name__ == "__main__":
    main()
