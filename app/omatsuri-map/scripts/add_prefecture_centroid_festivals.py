#!/usr/bin/env python3
"""jawiki記事リードから都道府県名を抽出し、centroid座標を付与して新規候補を生成する。

推測値禁止方針:
  - 記事リードに都道府県名が明示されていないものは除外する
  - 都道府県centroid(bounding-box中心、離島型6県は県庁所在地代表)を座標とする
  - coordinate_source = "prefecture_centroid"
"""
import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

_spec = importlib.util.spec_from_file_location("s", "scripts/discover_sparql_festivals.py")
s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s)

_spec2 = importlib.util.spec_from_file_location("v", "scripts/validate_prefecture_coordinates.py")
v = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(v)

_spec3 = importlib.util.spec_from_file_location("im", "scripts/import_wikimedia_festivals.py")
im = importlib.util.module_from_spec(_spec3)
_spec3.loader.exec_module(im)

PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]
PREF_RE = re.compile("(?:" + "|".join(re.escape(p) for p in PREFECTURES) + ")")

# 湾の奥に県庁があり、最大リング頂点平均が県外出る3県の実在代表点（境界で検証済み）
FALLBACK_COORDINATES = {
    "高知県":   (33.56, 133.53),
    "長崎県":   (32.752, 129.8449),
    "鹿児島県": (31.56, 130.55),
}
CENTROID_TABLE = {}

def _largest_ring(feature):
    geometry = feature.get("geometry", {})
    coordinates = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        return coordinates[0]
    return max((poly[0] for poly in coordinates), key=len)

def build_centroid_table(features):
    for pref in PREFECTURES:
        f = next(x for x in features if x.get("properties", {}).get("nam_ja") == pref)
        ring = _largest_ring(f)
        lat = round(sum(p[1] for p in ring) / len(ring), 6)
        lng = round(sum(p[0] for p in ring) / len(ring), 6)
        if v.containing_prefecture(lng, lat, features) == pref:
            CENTROID_TABLE[pref] = (lat, lng)
            continue
        fallback = FALLBACK_COORDINATES.get(pref)
        if fallback and v.containing_prefecture(fallback[1], fallback[0], features) == pref:
            CENTROID_TABLE[pref] = fallback
        else:
            print(f"WARNING: no in-bounds point for {pref}", file=sys.stderr)
    return CENTROID_TABLE


def fetch_article_texts(session, titles, batch_size=20):
    texts = {}
    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        data = session.get(
            "https://ja.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
                "exsentences": "10",
                "titles": "|".join(batch),
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            },
            timeout=30,
        ).json()
        for page in data.get("query", {}).get("pages", []):
            title = page.get("title")
            text = page.get("extract", "")
            if title and text:
                texts[title] = text[:500]
        time.sleep(0.6)
    return texts


def extract_prefecture(text):
    m = PREF_RE.search(text)
    return m.group(0) if m else None


def collect_category_candidates(session, centroid_table, existing_qids, existing_titles):
    """カテゴリ(`Category:○○の祭り`)名から都道府県を確定できる座標なし QID を収集する。

    都道府県はカテゴリ付け由来のため、記事リードの推測より確実。
    同一 QID が複数県カテゴリに入っている(広域)場合は除外する。
    """
    title_prefectures = im.discover_titles(session)
    title_qids = im.fetch_qids(session, title_prefectures.keys())
    labels_by_qid = im.fetch_entities(session, set(title_qids.values()))
    results = {}
    for title, qid in title_qids.items():
        prefectures = title_prefectures.get(title, set())
        if len(prefectures) != 1:
            continue
        q = qid
        if q in existing_qids or title in existing_titles:
            continue
        if im.EXCLUDED_TITLE.search(title):
            continue
        if im.coordinate(labels_by_qid.get(q, {})):
            continue
        prefecture = next(iter(prefectures))
        centroid = centroid_table.get(prefecture)
        if not centroid:
            continue
        lat, lng = centroid
        entity = labels_by_qid.get(q, {})
        results[q] = {
            "qid": q,
            "label_ja": title,
            "label_en": entity.get("labels", {}).get("en", {}).get("value", ""),
            "prefecture": prefecture,
            "latitude": lat,
            "longitude": lng,
            "description": entity.get("descriptions", {}).get("ja", {}).get("value", ""),
            "date": "日付未定",
            "wikipedia_title": title,
            "coordinate_source": "prefecture_centroid",
            "coordinate_validation_source": "prefecture_bounding_box",
        }
    return results


def build_new_candidates(cands, texts, centroid_table, existing_qids):
    results = []
    for cand in cands:
        qid = cand["qid"]
        if qid in existing_qids:
            continue
        title = cand.get("title")
        text = texts.get(title, "")
        prefecture = extract_prefecture(text)
        if not prefecture:
            continue
        centroid = centroid_table.get(prefecture)
        if not centroid:
            continue
        lat, lng = centroid
        results.append({
            "qid": qid,
            "label_ja": title,
            "label_en": cand.get("label_en", ""),
            "prefecture": prefecture,
            "latitude": lat,
            "longitude": lng,
            "description": cand.get("description_ja", ""),
            "date": "日付未定",
            "wikipedia_title": title,
            "coordinate_source": "prefecture_centroid",
            "coordinate_validation_source": "prefecture_bounding_box",
        })
    order = {name: idx for idx, name in enumerate(PREFECTURES)}
    return sorted(results, key=lambda r: (order.get(r["prefecture"], 99), r["label_ja"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("frontend/festivals.json"))
    parser.add_argument("--merge", action="store_true", help="integrate into festivals.json")
    parser.add_argument("--out", type=Path, help="write candidates JSON to this path")
    args = parser.parse_args()

    existing = json.loads(args.data.read_text(encoding="utf-8"))
    existing_qids = {i["qid"] for i in existing if i.get("qid")}
    existing_titles = {i.get("wikipedia_title") for i in existing if i.get("wikipedia_title")}

    session = requests.Session()
    session.headers["User-Agent"] = s.USER_AGENT

    qids = s.sparql_qids(session)
    new_qids = qids - existing_qids
    entities = s.fetch_entities(session, new_qids)

    cands = []
    for qid, entity in entities.items():
        title = s.jawiki_title(entity)
        if not title or s.EXCLUDED_TITLE.search(title):
            continue
        if s.resolved_coordinate(entity, {}):
            continue
        if title in existing_titles:
            continue
        cands.append({
            "qid": qid,
            "title": title,
            "label_en": entity.get("labels", {}).get("en", {}).get("value", ""),
            "description_ja": entity.get("descriptions", {}).get("ja", {}).get("value", ""),
        })
    print(f"no-coord jawiki candidates: {len(cands)}", flush=True)

    print("fetching jawiki article extracts...", flush=True)
    texts = fetch_article_texts(session, [c["title"] for c in cands])
    print(f"articles with text: {len(texts)}", flush=True)

    print("building centroid table...", flush=True)
    features = v.fetch_features()
    build_centroid_table(features)
    missing = [p for p in PREFECTURES if p not in CENTROID_TABLE]
    if missing:
        print(f"WARNING: missing centroid for: {missing}", file=sys.stderr)

    lead_candidates = build_new_candidates(cands, texts, CENTROID_TABLE, existing_qids)
    print(f"candidates (prefecture from article lead): {len(lead_candidates)}", flush=True)

    print("collecting category-based candidates (Category:○○の祭り)...", flush=True)
    category_candidates = collect_category_candidates(session, CENTROID_TABLE, existing_qids, existing_titles)
    category_candidates = [r for r in category_candidates.values()]
    print(f"candidates (prefecture from category name): {len(category_candidates)}", flush=True)

    merged_by_qid = {}
    order = {name: idx for idx, name in enumerate(PREFECTURES)}
    for row in lead_candidates:
        merged_by_qid.setdefault(row["qid"], row)
    for row in category_candidates:
        existing_row = merged_by_qid.get(row["qid"])
        if existing_row:
            existing_row["prefecture"] = row["prefecture"]
            existing_row["latitude"], existing_row["longitude"] = row["latitude"], row["longitude"]
            merged_by_qid[row["qid"]] = existing_row
        else:
            merged_by_qid[row["qid"]] = row
    results = sorted(merged_by_qid.values(), key=lambda r: (order.get(r["prefecture"], 99), r["label_ja"]))
    print(f"merged candidates (deduped, category name preferred): {len(results)}", flush=True)

    out_path = args.out or Path("data/new_prefecture_centroid_candidates.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"candidates saved to: {out_path}", flush=True)

    pref_count = Counter(r["prefecture"] for r in results)
    print("\nprefecture distribution:")
    for pref, cnt in sorted(pref_count.items(), key=lambda x: -x[1]):
        print(f"  {pref}: {cnt}")

    if args.merge:
        import enrich_wikidata_dates as date_enricher
        import apply_verified_occurrences as verified_dates
        import apply_verified_venues as verified_venues
        merged = existing + results
        all_qids = {i["qid"] for i in merged if i.get("qid")}
        all_entities = s.fetch_entities(session, all_qids)
        cal_qids = [qid2 for e2 in all_entities.values() for qid2 in date_enricher.p837_qids(e2)]
        cal_entities = s.fetch_entities(session, cal_qids) if cal_qids else {}
        schedules = date_enricher.schedules_by_festival(all_entities, cal_entities)
        dated = date_enricher.enrich(merged, schedules)
        with_occ = verified_dates.apply_occurrences(dated)
        with_ven = verified_venues.apply_venues(with_occ)
        validated = v.apply_coordinate_prefectures(with_ven, features)
        v.write_json(args.data, validated)
        print(f"\nmerged and wrote {args.data}: total {len(validated)}, new schedules {len(schedules)}")
    else:
        print("\ndry run. pass --merge to update frontend/festivals.json")


if __name__ == "__main__":
    main()
