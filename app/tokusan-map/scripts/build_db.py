#!/usr/bin/env python3
"""frontend/tokusan.json に data/curation.json の選別を適用し、
検索用 SQLite (frontend/tokusan.db) に変換する。

curation.json の include に載った品目だけを掲載し、カテゴリ・場所・座標は
include の値で上書きする。exclude には掲載しない理由を記録する。
tokusan.json のすべての qid がどちらかに載っていないと失敗する。
"""
import json
import sqlite3
import sys
import time
import re
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse
from import_production_points import apply_points
from classify_regions import classify, export_public, load_regions

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "tokusan.json"
CURATION = ROOT / "data" / "curation.json"
OFFICIAL = ROOT / "data" / "official.json"
DST = ROOT / "frontend" / "tokusan.db"
CATEGORIES = {"sa", "te", "ui", "sa2", "am", "ko", "ry", "ta", "or", "ri", "kg", "nk", "sz", "se", "ka"}
sys.path.insert(0, str(ROOT.parent / "omatsuri-map" / "scripts"))
SCHEMA = """
DROP TABLE IF EXISTS tokusan;
CREATE TABLE tokusan (
  id INTEGER PRIMARY KEY,
  qid TEXT NOT NULL UNIQUE,
  label_ja TEXT NOT NULL,
  label_en TEXT NOT NULL DEFAULT '',
  place TEXT NOT NULL DEFAULT '',
  prefecture TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  lat REAL NOT NULL DEFAULT 0,
  lng REAL NOT NULL DEFAULT 0,
  evidence TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  source_url TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  maker TEXT NOT NULL DEFAULT '',
  prefecture_level INTEGER NOT NULL DEFAULT 0,
  source_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  production_area TEXT NOT NULL DEFAULT '',
  coordinate_kind TEXT NOT NULL DEFAULT '',
  coordinate_label TEXT NOT NULL DEFAULT '',
  coordinate_source_url TEXT NOT NULL DEFAULT '',
  coordinate_source_name TEXT NOT NULL DEFAULT '',
  region_ids TEXT NOT NULL DEFAULT '[]',
  region_scope TEXT NOT NULL DEFAULT 'unknown',
  region_basis TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_tokusan_prefecture ON tokusan(prefecture);
CREATE INDEX idx_tokusan_category ON tokusan(category);
"""


def validate(rows, curation, official=()):
    """選別の漏れ・不正値を列挙する。問題がなければ空リストを返す."""
    from validate_prefecture_coordinates import containing_prefecture, fetch_features

    include, exclude = curation["include"], curation["exclude"]
    qids = {r["qid"] for r in rows}
    errors = [f"{q}: include と exclude の両方にある" for q in include.keys() & exclude.keys()]
    errors += [f"{q}: curation.json で未判定" for q in sorted(qids - include.keys() - exclude.keys())]
    errors += [f"{q}: tokusan.json に存在しない" for q in sorted((include.keys() | exclude.keys()) - qids)]
    errors += [f"{q}: 除外理由が空" for q, e in exclude.items() if not e.get("reason")]
    for attempt in range(3):
        try:
            features = fetch_features()
            break
        except Exception as exc:  # noqa: BLE001 - 取得失敗は再試行し、最後に理由を示して止める
            if attempt == 2:
                raise SystemExit(f"都道府県境界 GeoJSON を取得できない: {exc}")
            time.sleep(2 + 3 * attempt)
    for q, e in include.items():
        if e.get("category") not in CATEGORIES:
            errors.append(f"{q}: 不正なカテゴリ {e.get('category')!r}")
        if not e.get("wiki_title"):
            errors.append(f"{q}: wiki_title が空")
        maker = e.get("maker", "")
        if not isinstance(maker, str):
            errors.append(f"{q}: maker は文字列であるべき {maker!r}")
        lat, lng = e.get("lat") or 0, e.get("lng") or 0
        if not lat or not lng:
            errors.append(f"{q}: 座標がない")
            continue
        got = containing_prefecture(lng, lat, features)
        if got != e.get("prefecture"):
            errors.append(f"{q}: 座標が {got} にあり、prefecture={e.get('prefecture')} と一致しない")
    ids = set(qids)
    labels = {e.get('label') or r.get('label_ja', '') for r in rows if (e := include.get(r['qid']))}
    for e in official:
        item_id = e.get('id', '')
        if not re.fullmatch(r'local-[a-f0-9]{16}', item_id) or item_id in ids:
            errors.append(f'{item_id}: 不正または重複したID')
        ids.add(item_id)
        for key in ('label', 'prefecture', 'place', 'description', 'source_name', 'source_checked_at', 'production_area'):
            if not isinstance(e.get(key), str) or not e[key].strip():
                errors.append(f'{item_id}: {key} が空')
        if e.get('label') in labels:
            errors.append(f'{item_id}: 品目名が重複 {e.get("label")}')
        labels.add(e.get('label'))
        source = urlparse(e.get('source_url', ''))
        if source.scheme != 'https' or not source.hostname or source.username or source.password:
            errors.append(f'{item_id}: 不正な出典URL')
        if e.get('category') not in CATEGORIES:
            errors.append(f'{item_id}: 不正なカテゴリ')
        got = containing_prefecture(e.get('lng', 0), e.get('lat', 0), features)
        if got != e.get('prefecture'):
            errors.append(f'{item_id}: 座標が {got} にあり、prefecture={e.get("prefecture")} と一致しない')
        if not e.get('prefecture_level') and e.get('coordinate_kind') not in ('municipality_office', 'named_area_office'):
            errors.append(f'{item_id}: 産地代表座標の根拠がない')
    return errors


def main():
    if not SRC.exists():
        raise SystemExit(f"入力ファイルが見つからない: {SRC}")
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    curation = json.loads(CURATION.read_text(encoding="utf-8"))
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    points = json.loads((ROOT / 'data/production_points.json').read_text(encoding='utf-8'))
    official = apply_points(official, points)
    errors = validate(rows, curation, official)
    if errors:
        raise SystemExit("curation.json の検証に失敗:\n  " + "\n  ".join(errors))
    include = curation["include"]
    # Build beside the deployed DB, then replace it atomically. Existing readers
    # keep their old snapshot until the server restarts.
    fd, temporary = tempfile.mkstemp(prefix='tokusan-', suffix='.db', dir=DST.parent)
    os.close(fd)
    con = sqlite3.connect(temporary)
    con.executescript(SCHEMA)
    for r in rows:
        e = include.get(r["qid"])
        if e is None:
            continue
        # 場所を上書きした品目では、LLM の根拠と信頼度は別の場所についての値なので捨てる
        same_place = e["place"] == r.get("place", "")
        con.execute(
            "INSERT INTO tokusan (qid, label_ja, label_en, place, prefecture,"
            " city, lat, lng, evidence, confidence, source_url, category,"
            " maker, prefecture_level)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["qid"],
                e.get("label") or r.get("label_ja", ""),
                r.get("label_en", ""),
                e["place"],
                e["prefecture"],
                e.get("city", ""),
                float(e["lat"]),
                float(e["lng"]),
                r.get("evidence", "") if same_place else "",
                float(r.get("confidence") or 0) if same_place else 0.0,
                "https://ja.wikipedia.org/wiki/" + quote(e["wiki_title"].replace(" ", "_")),
                e["category"],
                e.get("maker", ""),
                1 if e.get("prefecture_level") else 0,
            ),
        )
    for e in official:
        con.execute(
            'INSERT INTO tokusan (qid, label_ja, place, prefecture, lat, lng, source_url, category,'
            ' prefecture_level, source_name, description, production_area, maker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (e['id'], e['label'], e['place'], e['prefecture'], e['lat'], e['lng'], e['source_url'],
             e['category'], int(e['prefecture_level']), e['source_name'], e['description'], e['production_area'], e.get('maker', '')),
        )
        if e.get('coordinate_kind'):
            con.execute('UPDATE tokusan SET city=?, coordinate_kind=?, coordinate_label=?, '
                        'coordinate_source_url=?, coordinate_source_name=? WHERE qid=?',
                        (e['city'], e['coordinate_kind'], e['coordinate_label'],
                         e['coordinate_source_url'], e['coordinate_source_name'], e['id']))
    con.execute("UPDATE tokusan SET source_name = 'Wikipedia' WHERE source_name = ''")
    definitions = load_regions()
    by_prefecture = {p['prefecture']: p for p in definitions}
    for qid, prefecture, area, city, place in con.execute('SELECT qid, prefecture, production_area, city, place FROM tokusan').fetchall():
        region_ids, scope, basis = classify(area or city or place, prefecture, by_prefecture[prefecture])
        con.execute('UPDATE tokusan SET region_ids=?, region_scope=?, region_basis=? WHERE qid=?',
                    (json.dumps(region_ids), scope, basis, qid))
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM tokusan").fetchone()[0]
    pref = con.execute(
        "SELECT COUNT(*) FROM tokusan WHERE prefecture_level = 1"
    ).fetchone()[0]
    cats = con.execute("SELECT category, COUNT(*) FROM tokusan GROUP BY category ORDER BY category")
    cat_str = ", ".join(f"{c[0] or '(空)' }={c[1]}" for c in cats)
    con.close()
    # Cloud Run's distroless image runs as nonroot; COPY preserves this mode.
    os.chmod(temporary, 0o644)
    os.replace(temporary, DST)
    export_public(definitions)
    print(f"tokusan.db: 品目 {count} 件 (都道府県単位 {pref} 件、除外 {len(curation['exclude'])} 件) -> {DST}")
    print(f"  カテゴリ: {cat_str}")


if __name__ == "__main__":
    main()
