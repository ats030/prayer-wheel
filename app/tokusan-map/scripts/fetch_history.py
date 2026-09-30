#!/usr/bin/env python3
"""Backfill the history section of MAFF cuisine and traditional-food pages.

Reads data/official.json, fetches each cuisine/traditional source page and saves
the 「歴史・由来・関連行事」 / 「歴史・文化、関連行事」 text (paragraphs kept) into
data/history.json keyed by source URL. Resumable: fetched URLs are skipped.
"""
import json
import re
import sys
import time
from html import unescape
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "data" / "official.json"
OUT = ROOT / "data" / "history.json"
KINDS = {"cuisine", "traditional"}
HEADINGS = ("歴史・由来・関連行事", "歴史・文化、関連行事")
# Sections quoting third-party material are not covered by the PDL1.0 review.
THIRD_PARTY = ("資料：", "出典：", "提供：", "引用：")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "TokusanMap/1.0 (https://github.com/ats030/tokusan-map)"


def fetch(url):
    for attempt in range(4):
        try:
            response = SESSION.get(url, timeout=40)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            response.encoding = "utf-8"
            return response.text
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            print(f"retry {url} ({exc})", flush=True)
            time.sleep(2 * (attempt + 1))


def clean(fragment):
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</p\s*>", "\n", fragment, flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", "", fragment))
    lines = [re.sub(r"[ \t　\r]+", "", line) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def extract(html_text):
    for heading in HEADINGS:
        m = re.search(r"<h3[^>]*>(?:(?!</h3>).)*" + re.escape(heading) + r".*?</h3>(.*?)(?=<h3|</li>|</div>)",
                      html_text, re.S)
        if m:
            return clean(m.group(1))
    return ""


def main():
    entries = [e for e in json.loads(OFFICIAL.read_text()) if e.get("source_kind") in KINDS]
    saved = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [e["source_url"] for e in entries if e["source_url"] not in saved]
    print(f"targets={len(entries)} saved={len(saved)} todo={len(todo)}", flush=True)
    for n, url in enumerate(todo, 1):
        html_text = fetch(url)
        text = extract(html_text) if html_text else ""
        status = "ok" if text else ("missing" if html_text else "404")
        if text and any(marker in text for marker in THIRD_PARTY):
            text, status = "", "third_party"
        saved[url] = {"history": text, "status": status}
        if n % 25 == 0 or n == len(todo):
            OUT.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n")
            print(f"{n}/{len(todo)}", flush=True)
        time.sleep(1.0)
    counts = {}
    for v in saved.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
