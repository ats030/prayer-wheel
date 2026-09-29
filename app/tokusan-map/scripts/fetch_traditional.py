#!/usr/bin/env python3
"""Scrape MAFF 'nippoun dentou shoku zukan' area indexes and menu pages."""
import json
import re
import time
from html import unescape
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "traditional_candidates.json"
BASE = "https://www.maff.go.jp/j/keikaku/syokubunka/traditional-foods"
# Only participating prefectures appear on the index page; resolve name per code.
PREF_NAMES = {
    "hokkaido": "北海道", "aomori": "青森県", "iwate": "岩手県", "miyagi": "宮城県",
    "akita": "秋田県", "yamagata": "山形県", "fukushima": "福島県",
    "ibaraki": "茨城県", "tochigi": "栃木県", "gunma": "群馬県", "saitama": "埼玉県",
    "chiba": "千葉県", "tokyo": "東京都", "kanagawa": "神奈川県",
    "niigata": "新潟県", "toyama": "富山県", "ishikawa": "石川県", "fukui": "福井県",
    "yamanashi": "山梨県", "nagano": "長野県", "gifu": "岐阜県", "shizuoka": "静岡県",
    "aichi": "愛知県", "mie": "三重県",
    "shiga": "滋賀県", "kyoto": "京都府", "osaka": "大阪府", "hyogo": "兵庫県",
    "nara": "奈良県", "wakayama": "和歌山県",
    "tottori": "鳥取県", "shimane": "島根県", "okayama": "岡山県", "hiroshima": "広島県",
    "yamaguchi": "山口県", "tokushima": "徳島県", "kagawa": "香川県",
    "ehime": "愛媛県", "kochi": "高知県",
    "fukuoka": "福岡県", "saga": "佐賀県", "nagasaki": "長崎県", "kumamoto": "熊本県",
    "oita": "大分県", "miyazaki": "宮崎県", "kagoshima": "鹿児島県", "okinawa": "沖縄県",
}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "TokusanMap/1.0 (https://github.com/ats030/tokusan-map)"


def fetch(url):
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=40)
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


def fields(html_text):
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S)
    body = strip(html_text)

    def grab(label, enders):
        m = re.search(re.escape(label) + r"\s*(.{1,400}?)(?=" + "|".join(enders) + ")", body)
        return strip(m.group(1)) if m else ""

    return {
        "label": strip(h1.group(1)).replace("｜", "").replace("にっぽん伝統食図鑑", "") if h1 else "",
        "class_big": grab("分類(大)", ["分類\\(小\\)|主な使用食材|主な伝承地域|食品概要"]),
        "class_small": grab("分類(小)", ["主な使用食材|主な伝承地域|食品概要"]),
        "ingredients": grab("主な使用食材", ["主な伝承地域|食品概要|歴史"]),
        "production_area": grab("主な伝承地域", ["食品概要|歴史|製造方法|主な使用食材|分類"]),
        "overview": grab("食品概要", ["歴史|製造方法|主な食材|分類"]),
    }


def main():
    index = fetch(BASE + "/")
    codes = list(dict.fromkeys(re.findall(r'href="area/([a-z]+)\.html"', index)))
    print(f"participating: {len(codes)} -> {codes}")
    entries, done = [], set()
    if OUT.exists():
        for e in json.loads(OUT.read_text()):
            entries.append(e)
            done.add(e["url"])
        print(f"resume: {len(entries)} saved")
    for code in codes:
        prefecture = PREF_NAMES.get(code, code)
        area_url = f"{BASE}/area/{code}.html"
        try:
            area = fetch(area_url)
        except Exception as exc:
            print(f"FAIL area {code}: {exc}")
            continue
        time.sleep(0.3)
        slugs = list(dict.fromkeys(re.findall(
            r'href="[^"]*/menu/([a-z0-9_]+)\.html"', area)))
        print(f"{prefecture}: {len(slugs)} items")
        for slug in slugs:
            url = f"{BASE}/menu/{slug}.html"
            if url in done:
                continue
            try:
                text = fetch(url)
            except Exception as exc:
                print(f"FAIL menu {url}: {exc}")
                continue
            time.sleep(0.25)
            f = fields(text)
            entries.append({
                "prefecture": prefecture, "label": f["label"],
                "class_big": f["class_big"], "class_small": f["class_small"],
                "ingredients": f["ingredients"], "production_area": f["production_area"],
                "overview": f["overview"], "url": url,
                "ok": bool(f["label"] and (f["production_area"] or f["ingredients"])),
            })
            done.add(url)
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
    ok = sum(e["ok"] for e in entries)
    print(f"saved {len(entries)} ({ok} ok) -> {OUT}")


if __name__ == "__main__":
    main()
