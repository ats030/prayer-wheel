"""Build the geosite table of geo.db: natural monuments designated under the geology and mineral criteria.

The 文化庁 CSV has no criteria column, so each detail page is fetched once (1 second apart) and cached in
~/cache/geo-map; rerunning without --refresh reads only the cache.
"""
import argparse
import csv
import html
import io
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from geodb import replace_tables

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / "cache/geo-map"
BASE = "https://kunishitei.bunka.go.jp"
# Keep 管理対象ID as written in the CSV: stripping the zero padding of newer IDs redirects to an error page.
DETAIL_URL = BASE + "/heritage/detail/401/{}"
SOURCE_NAME = "文化庁 国指定文化財等データベース"
USER_AGENT = "MidokoroMap/1.0 (https://github.com/ats030)"
KINDS = {"entry_kind1_401[2]": "天然記念物", "entry_kind1_401[5]": "特別天然記念物"}
HIDDEN = re.compile(r'<input type="hidden" name="([^"]+)"(?: autocomplete="off")? value="([^"]*)"')
TOKEN = re.compile(r'name="_csrfToken"[^>]*value="([^"]+)"')
# 天然記念物 指定基準 地質鉱物 (一)-(十二). Matched as whole phrases: 植物 (九) and 名勝 「五．岩石、洞穴」 share words.
GEOLOGY = ("岩石、鉱物及び化石の産出状態", "地層の整合及び不整合", "地層の摺曲及び衝上", "生物の働きによる地質現象",
           "地震断層など地塊運動", "（六）洞穴", "岩石の組織", "温泉並びにその沈澱物", "風化及び侵蝕",
           "硫気孔及び火山活動", "氷雪霜", "岩石、鉱物及び化石の標本")
BIOLOGY = ("動物", "植物", "名木", "原始林", "群落", "自生地", "棲息地", "繁殖地", "渡来地", "藻類", "限界地", "畜養", "家禽")


def criteria(page: str) -> str | None:
    """Return the 指定基準 text of a detail page, '' when the field is empty, None when the page has no such field."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", page))
    m = re.search(r"指定基準 ：\s?(.*?)\s?所在都道府県", text)
    return html.unescape(m.group(1)).strip() if m else None


def classify(text: str | None) -> str:
    if not text:
        return "unknown"
    geology = any(p in text for p in GEOLOGY)
    biology = any(p in text for p in BIOLOGY)
    return "geo+bio" if geology and biology else "geo" if geology else "bio" if biology else "other"


def coordinates(item: dict) -> tuple[float, float] | tuple[None, None]:
    try:
        return float(item["緯度"]), float(item["経度"])
    except ValueError:
        return None, None


def designation(item: dict) -> str:
    return "special" if "特別天然記念物" in (item["種別1"], item["種別2"]) else "national"


def build(refresh: bool, out_path: Path) -> dict:
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    last = [0.0]

    def request(method: str, url: str, check: bool = True, **kwargs):
        time.sleep(max(0.0, last[0] + 1 - time.monotonic()))
        response = session.request(method, url, timeout=120, **kwargs)
        last[0] = time.monotonic()
        if check:
            response.raise_for_status()
        return response

    folder = CACHE / "tennen"
    folder.mkdir(parents=True, exist_ok=True)
    csv_path, meta_path = folder / "tennen.csv", folder / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.setdefault("pages", {})
    if refresh or not csv_path.exists():
        index = request("GET", BASE + "/bsys/index")
        listing = request("POST", BASE + "/bsys/searchlist", data={
            "_method": "POST", "_csrfToken": TOKEN.search(index.text).group(1), "screen_id": "index",
            "page_no": "1", "register_sub_id": "401", **KINDS})
        start = listing.text.index('action="/utile/csv-list"')
        form = listing.text[start:listing.text.index("</form>", start)]
        text = request("POST", BASE + "/utile/csv-list", data=HIDDEN.findall(form)).content.decode("utf-8-sig")
        if not text.lstrip('"').startswith("台帳ID"):
            raise ValueError("unexpected CSV header: " + text[:200])
        csv_path.write_text(text, encoding="utf-8")
        meta = {"csv": date.today().isoformat(), "pages": {}}
    items = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))

    pages = CACHE / "tennen-detail"
    pages.mkdir(parents=True, exist_ok=True)
    report = {"monuments": len(items), "fetched": 0, "bad_url": {}, "kinds": Counter(), "without_coordinates": 0}
    rows = []
    for item in items:
        hid = item["管理対象ID"]
        path, url = pages / f"{hid}.html", DETAIL_URL.format(hid)
        record = meta["pages"].get(hid)
        if refresh or not record or not path.exists():
            response = request("GET", url, check=False)
            record = {"fetched": date.today().isoformat(), "status": response.status_code,
                      "redirected": bool(response.history), "final_url": response.url}
            path.write_text(response.text, encoding="utf-8")
            report["fetched"] += 1
            # The site sometimes answers with a transient error redirect; leave it unrecorded so the next run retries.
            if record["status"] == 200 and not record["redirected"]:
                meta["pages"][hid] = record
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        page = path.read_text(encoding="utf-8")
        text = criteria(page)
        if record["status"] != 200 or record["redirected"] or text is None:
            report["bad_url"][hid] = record["final_url"]
        kind = classify(text)
        report["kinds"][kind] += 1
        if not kind.startswith("geo"):
            continue
        lat, lon = coordinates(item)
        report["without_coordinates"] += lat is None
        rows.append((hid, item["名称"].split("\n")[0].strip(), designation(item),
                     "・".join(k for k in (item["種別1"], item["種別2"]) if k), kind, text, item["都道府県"],
                     item["所在地"], lat, lon, url, record["fetched"]))
    report["geosites"] = len(rows)
    report["kinds"] = dict(report["kinds"])
    if report["bad_url"]:
        # Missing criteria would silently drop monuments; keep the previous table instead.
        return report
    replace_tables(out_path, """
        create table geosite(heritage_id text primary key, name text not null, designation text not null,
            designation_label text not null, kind text not null, criteria text not null, prefecture text not null,
            address text not null, latitude real, longitude real, source_url text not null, fetched text not null);
    """, {"geosite": rows}, {
        "geosite_source": f"{SOURCE_NAME} ({BASE}/bsys/index)", "geosite_list_fetched": meta.get("csv", ""),
        "geosite_counts": json.dumps(dict(report["kinds"]), ensure_ascii=False, sort_keys=True),
        "geosite_built": date.today().isoformat()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="refetch the CSV and every detail page")
    parser.add_argument("--out", type=Path, default=ROOT / "data/geo.db")
    args = parser.parse_args()
    report = build(args.refresh, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["bad_url"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
