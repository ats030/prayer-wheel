#!/usr/bin/env python3
"""Scrape MAFF 'uchi no kyoudo ryouri' area indexes and menu pages."""
import json
import re
import time
from html import unescape
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "k_ryouri_candidates.json"
BASE = "https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/search_menu"
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県",     "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県",
    "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
CODES = {
    "北海道": "hokkaido", "青森県": "aomori", "岩手県": "iwate", "宮城県": "miyagi",
    "秋田県": "akita", "山形県": "yamagata", "福島県": "fukushima",
    "茨城県": "ibaraki", "栃木県": "tochigi", "群馬県": "gunma", "埼玉県": "saitama",
    "千葉県": "chiba", "東京都": "tokyo", "神奈川県": "kanagawa",
    "新潟県": "niigata", "富山県": "toyama", "石川県": "ishikawa", "福井県": "fukui",
    "山梨県": "yamanasi", "長野県": "nagano", "岐阜県": "gifu", "静岡県": "shizuoka",
    "愛知県": "aichi", "三重県": "mie",
    "滋賀県": "shiga", "京都府": "kyoto", "大阪府": "osaka", "兵庫県": "hyogo",
    "奈良県": "nara", "和歌山県": "wakayama",
    "鳥取県": "tottori", "島根県": "shimane", "岡山県": "okayama", "広島県": "hiroshima",
    "山口県": "yamaguchi",
    "徳島県": "tokushima", "香川県": "kagawa", "愛媛県": "ehime", "高知県": "kochi",
    "福岡県": "fukuoka", "佐賀県": "saga", "長崎県": "nagasaki", "熊本県": "kumamoto",
    "大分県": "oita", "宮崎県": "miyazaki", "鹿児島県": "kagoshima", "沖縄県": "okinawa",
}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "TokusanMap/1.0 (https://github.com/ats030/tokusan-map)"


def fetch(url):
    session = SESSION
    for attempt in range(4):
        try:
            response = session.get(url, timeout=40)
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            print(f"retry {url} ({exc})")
            time.sleep(2 * (attempt + 1))


def strip(text):
    text = re.sub(r"<[^>]+>", " ", unescape(text))
    return re.sub(r"\s+", "", text)


def menu_fields(html_text):
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S)
    body = strip(html_text)
    region = re.search(r"主な伝承地域\s*(.{1,120}?)(?=主な使用食材|歴史|食習|主な伝承)", body)
    ingredients = re.search(r"主な使用食材\s*(.{1,400}?)(?=歴史|食習|関連行事)", body)
    return h1, region, ingredients


def main():
    entries = []
    done = set()
    if OUT.exists():
        for e in json.loads(OUT.read_text()):
            entries.append(e)
            done.add(e["url"])
        print(f"resume: {len(entries)} already saved")
    for prefecture in PREFECTURES:
        area_url = f"{BASE}/area/{CODES[prefecture]}.html"
        try:
            area = fetch(area_url)
        except Exception as exc:
            print(f"FAIL area {prefecture}: {exc}")
            continue
        time.sleep(0.25)
        slugs = list(dict.fromkeys(re.findall(r'href="\.\./menu/([a-z0-9_]+)\.html"', area)))
        print(f"{prefecture}: {len(slugs)} items")
        for slug in slugs:
            url = f"https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/search_menu/menu/{slug}.html"
            if url in done:
                continue
            try:
                text = fetch(url)
            except Exception as exc:
                print(f"FAIL menu {url}: {exc}")
                continue
            time.sleep(0.15)
            h1, region, ingredients = menu_fields(text)
            label = ""
            if h1:
                label = strip(h1.group(1))
                label = re.sub(re.escape(prefecture) + "$", "", label)
            entries.append({
                "prefecture": prefecture, "label": label,
                "production_area": strip(region.group(1)) if region else "",
                "ingredients": strip(ingredients.group(1)) if ingredients else "",
                "url": url, "ok": bool(h1 and region),
                "title_raw": strip(h1.group(1)) if h1 else "",
                "region_raw": strip(region.group(1)) if region else "",
                "ingredients_raw": strip(ingredients.group(1)) if ingredients else "",
            })
            done.add(url)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
    ok = sum(e["ok"] for e in entries)
    print(f"saved {len(entries)} candidates ({ok} ok) -> {OUT}")


if __name__ == "__main__":
    main()
