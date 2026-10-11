"""Build the geopark table of geo.db from geopark.jp and MLIT N03 boundaries.

Pages and boundary archives are cached in ~/cache/geo-map; rerunning without --refresh reads only the cache.
"""
import argparse
import html
import json
import re
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

from geodb import replace_tables

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / "cache/geo-map"
BASE = "https://geopark.jp/geopark/"
N03 = "N03-20260101"
N03_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/{}_{}_GML.zip"
USER_AGENT = "MidokoroMap/1.0 (https://github.com/ats030)"
NOT_REGIONS = {"about", "access", "certification", "pamphlet", "geopark"}
# Tolerance in degrees (about 50 m) keeps point membership close to the original boundary.
SIMPLIFY = 0.0005
DISPLAY_SIMPLIFY = 0.005
# Regions whose list-page count disagrees with the region page; the region page is treated as authoritative.
KNOWN_COUNT_GAPS = {"m_alps": "一覧の areaname は富士見町を含む2市1町1村、地域ページの構成自治体名は2市1村 (2026-10-11)"}
PREFS = ("北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 "
         "富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 "
         "鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 "
         "鹿児島県 沖縄県").split()
PCODE = {p: f"{i + 1:02d}" for i, p in enumerate(PREFS)}
PREF = r"(北海道|東京都|京都府|大阪府|[^\s、・，,：:|]{2,3}県)"


def regions(listing: str) -> dict[str, dict]:
    """Return {slug: {name, years}} for the regions shown on the list page; commented-out regions are withdrawn."""
    listing = re.sub(r"<!--.*?-->", "", listing, flags=re.S)
    out = {}
    for slug, title, rest in re.findall(r'<a href="(?:/geopark/)?([a-z][a-z0-9_-]*)/">\s*<img [^>]*?title="([^"]*)"([^>]*)>', listing):
        if slug in NOT_REGIONS:
            continue
        years = dict(re.findall(r'data-(jgn|ggn|unesco_ggn)year="([^"]*)"', rest))
        out[slug] = {"name": html.unescape(title.split("<")[0]).strip(),
                     "certified": years.get("jgn", "").split("：")[-1].removesuffix("認定"),
                     "unesco": bool(years.get("unesco_ggn")),
                     # 「（1市4町3村）」 gives the municipality count used to check the region page parse.
                     "count": sum(int(n) for n in re.findall(r"(\d+)[市町村]", title.split("（")[-1]))}
    for slug in sorted(set(re.findall(r'href="(?:/geopark/)?([a-z][a-z0-9_-]*)/"', listing)) - NOT_REGIONS - set(out)):
        out[slug] = {"name": "", "certified": "", "unesco": False, "count": 0}
    return out


def municipalities(page: str) -> dict:
    """Parse the 構成自治体名 section into [pref, district, name] triples and partially included names."""
    page = html.unescape(page)
    i = page.find("構成自治体名")
    if i < 0:
        raise ValueError("構成自治体名 not found")
    ends = [k for k in (page.find("お問合せ先", i), page.find("推進組織体制", i)) if k > 0]
    if not ends:
        raise ValueError("end of 構成自治体名 not found")
    j = min(ends)
    section = re.sub(r"<[^>]+>", "、", page[i + 6:j])
    contact = re.search(r"〒\d{3}-\d{4}\s*" + PREF, page[j:]) or re.search(r"〒\d{3}-\d{4}\s*(鹿児島)市", page[j:])
    pref = contact.group(1) if contact else ""
    pref = "鹿児島県" if pref == "鹿児島" else pref
    munis, partial, listed, pending = [], [], [], []
    last_muni = None
    for token in re.split(r"([（(][^）)]*[）)]|[、・，,：:\s])", section):
        if not token or re.fullmatch(r"[、・，,：:\s]", token):
            continue
        # 「…（以上宮崎県）」 applies to the municipalities listed since the previous marker.
        m = re.fullmatch(r"[（(]以上" + PREF + r"[）)]", token)
        if m:
            for x in pending:
                x[0] = m.group(1)
            pending = []
            last_muni = None
            continue
        if re.fullmatch(r"[（(][^）)]*[）)]", token):
            if last_muni is not None and re.search(r"一部|地域|エリア", token) and last_muni not in partial:
                partial.append(last_muni)
            continue
        last_muni = None
        m = re.match(PREF + r"(.*)$", token)
        if m and not m.group(2):
            pref = m.group(1)
            listed.append(pref)
            continue
        if m:
            pref, token = m.group(1), m.group(2)
        district = ""
        m = re.match(r"(.+?郡)(.+)$", token)
        if m:
            district, token = m.groups()
        is_partial = token.endswith("の一部")
        if is_partial:
            token = token[:-3]
        if re.fullmatch(r".+[市町村]", token):
            x = [pref, district, token]
            munis.append(x)
            pending.append(x)
            last_muni = x
            if is_partial:
                partial.append(x)
    return {"munis": munis, "partial": partial, "listed": listed}


def boundaries(pref_code: str, fetch) -> dict[tuple[str, str], list]:
    """Return {(district, municipality): [geometry]} for one prefecture, merging the wards of designated cities."""
    from shapely.geometry import shape
    path = CACHE / "n03" / f"{pref_code}.zip"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(fetch(N03_URL.format(N03, pref_code)))
    archive = zipfile.ZipFile(path)
    data = json.loads(archive.read(f"{N03}_{pref_code}.geojson"))
    out = {}
    for feature in data["features"]:
        p = feature["properties"]
        if not p["N03_004"] or not feature["geometry"]:
            continue
        code = p["N03_007"] or ""
        entry = out.setdefault((p["N03_003"] or "", p["N03_004"]), {"codes": set(), "shapes": []})
        entry["codes"].add(code[:4] + "0" if p["N03_005"] and code else code)
        entry["shapes"].append(shape(feature["geometry"]))
    return out


def resolve(muni: list, listed: list, lookup) -> tuple[str, str, dict] | None:
    """Find the N03 entry for [pref, district, name], trying the listed prefectures when the default misses."""
    pref, district, name = muni
    for candidate in dict.fromkeys([pref] + listed):
        if candidate not in PCODE:
            continue
        hits = [(key, entry) for key, entry in lookup(PCODE[candidate]).items()
                if key[1] == name and (not district or key[0] == district)]
        if len(hits) == 1:
            return candidate, hits[0][0][0], hits[0][1]
    return None


def display_boundary(area):
    """Preserve topology, omit tiny display islands, and keep at least the largest island."""
    from shapely.geometry import MultiPolygon
    simplified = area.simplify(DISPLAY_SIMPLIFY, preserve_topology=True)
    parts = list(simplified.geoms) if simplified.geom_type == 'MultiPolygon' else [simplified]
    visible = [part for part in parts if part.area >= DISPLAY_SIMPLIFY ** 2]
    return MultiPolygon(visible or [max(parts, key=lambda part: part.area)])


def build(refresh: bool, out_path: Path) -> dict:
    import requests
    from shapely import unary_union
    from shapely.geometry import mapping
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    last = [0.0]

    def fetch(url: str) -> bytes:
        time.sleep(max(0.0, last[0] + 1 - time.monotonic()))
        response = session.get(url, timeout=300)
        last[0] = time.monotonic()
        response.raise_for_status()
        return response.content

    pages = CACHE / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    meta_path = pages / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    def page(slug: str) -> str:
        path = pages / f"{slug or 'index'}.html"
        if refresh or not path.exists():
            path.write_bytes(fetch(BASE + (slug + "/" if slug else "")))
            meta[slug or "index"] = date.today().isoformat()
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        return path.read_text(encoding="utf-8")

    prefectures = {}

    def lookup(code: str):
        if code not in prefectures:
            prefectures[code] = boundaries(code, fetch)
        return prefectures[code]

    found = regions(page(""))
    report = {"regions": len(found), "unresolved": [], "partial": {}, "nameless": [], "count_mismatch": {}, "unparsed": {}}
    rows = []
    for slug, info in sorted(found.items()):
        text = page(slug)
        if not info["name"]:
            title = re.search(r"<title>([^|<]+)", text)
            info["name"] = title.group(1).strip() if title else slug
            report["nameless"].append(slug)
        try:
            parsed = municipalities(text)
        except ValueError as error:  # e.g. a new navigation link mistaken for a region
            report["unparsed"][slug] = str(error)
            continue
        members, shapes = [], []
        for muni in parsed["munis"]:
            hit = resolve(muni, parsed["listed"], lookup)
            if not hit:
                report["unresolved"].append(f"{slug}:{''.join(muni)}")
                continue
            pref, district, entry = hit
            partial = any(muni is item for item in parsed["partial"])
            members.append({"prefecture": pref, "district": district, "name": muni[2],
                            "code": min(entry["codes"]), "partial": partial})
            if not partial:
                shapes += entry["shapes"]
        if info["count"] and info["count"] != len(parsed["munis"]) and slug not in KNOWN_COUNT_GAPS:
            report["count_mismatch"][slug] = [info["count"], len(parsed["munis"])]
        if parsed["partial"]:
            report["partial"][slug] = ["".join(m) for m in parsed["partial"]]
        area = unary_union(shapes).simplify(SIMPLIFY, preserve_topology=True) if shapes else None
        rows.append((slug, info["name"], BASE + slug + "/", meta.get(slug, ""), info["certified"], int(info["unesco"]),
                     json.dumps(members, ensure_ascii=False),
                     json.dumps(mapping(area), separators=(",", ":")) if area else None,
                     *(area.bounds if area else (None,) * 4),
                     json.dumps(mapping(display_boundary(area)), separators=(",", ":")) if area else None))
    replace_tables(out_path, """
        create table geopark(slug text primary key, name text not null, source_url text not null, fetched text not null,
            certified text not null, unesco integer not null, municipalities text not null, geometry text,
            min_lon real, min_lat real, max_lon real, max_lat real, display_geometry text);
    """, {"geopark": rows}, {
        "geopark_source": BASE, "geopark_list_fetched": meta.get("index", ""),
        "boundary_source": f"国土数値情報 行政区域データ {N03} (https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html)",
        "display_simplify_degrees": str(DISPLAY_SIMPLIFY),
        "boundary_simplify_degrees": str(SIMPLIFY), "built": date.today().isoformat()})
    report["geoparks"] = len(rows)
    report["without_area"] = [r[0] for r in rows if r[7] is None]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="refetch geopark.jp pages instead of using the cache")
    parser.add_argument("--out", type=Path, default=ROOT / "data/geo.db")
    args = parser.parse_args()
    report = build(args.refresh, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if report["unresolved"] or report["without_area"] or report["count_mismatch"] or report["unparsed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
