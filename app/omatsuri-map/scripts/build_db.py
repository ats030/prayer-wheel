"""festivals.json から SQLite (frontend/festivals.db) を生成する。

カテゴリは frontend/app.js が読む categories 配列(先頭=代表カテゴリ)を
取り扱い、祭り×カテゴリの N:N として festival_categories に分解して保存する。
venue・occurrences・annual_schedule・cultural_relaw は構造が単一オブジェクト／
配列のため、そのまま JSON テキストとして列に保持する。
"""

import json
import sqlite3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "festivals.json"
DST = ROOT / "frontend" / "festivals.db"


SCHEMA = """
DROP TABLE IF EXISTS festival_categories;
DROP TABLE IF EXISTS category_types;
DROP TABLE IF EXISTS festival;

CREATE TABLE festival (
    id              INTEGER PRIMARY KEY,
    qid             TEXT NOT NULL UNIQUE,
    label_ja        TEXT NOT NULL,
    label_en        TEXT NOT NULL DEFAULT '',
    prefecture      TEXT NOT NULL DEFAULT '',
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    date            TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    wikipedia_title TEXT NOT NULL DEFAULT '',
    venue_json      TEXT NOT NULL DEFAULT '',
    occurrences_json  TEXT NOT NULL DEFAULT '',
    annual_schedule_json TEXT NOT NULL DEFAULT '',
    cultural_relaw_json TEXT NOT NULL DEFAULT '',
    lifecycle_json  TEXT NOT NULL DEFAULT '',
    description_source TEXT NOT NULL DEFAULT '',
    coordinate_source TEXT NOT NULL DEFAULT '',
    coordinate_prefecture TEXT NOT NULL DEFAULT '',
    coordinate_validation_source TEXT NOT NULL DEFAULT '',
    jalan_lrg_code  TEXT NOT NULL DEFAULT '',
    jalan_lrg_name  TEXT NOT NULL DEFAULT '',
    jalan_sml_code  TEXT NOT NULL DEFAULT '',
    jalan_sml_name  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_festival_prefecture ON festival (prefecture);

CREATE TABLE category_types (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE festival_categories (
    festival_id INTEGER NOT NULL REFERENCES festival(id),
    type_id     INTEGER NOT NULL REFERENCES category_types(id),
    PRIMARY KEY (festival_id, type_id)
);
CREATE INDEX idx_fc_type ON festival_categories (type_id);
"""


def dump(value):
    """None / 空は空文字列、それ以外は紧凑JSON。"""
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False)


def build():
    if not SRC.exists():
        raise SystemExit(f"source json not found: {SRC}")
    data = json.loads(SRC.read_text(encoding="utf-8"))

    if DST.exists():
        DST.unlink()

    conn = sqlite3.connect(DST)
    try:
        conn.executescript(SCHEMA)
        type_ids = {}
        tag_total = 0
        for e in data:
            qid = (e.get("qid") or "").strip()
            if not qid:
                raise SystemExit("entry without qid found")
            values = (
                qid,
                e.get("label_ja") or "",
                e.get("label_en") or "",
                e.get("prefecture") or "",
                float(e.get("latitude") or 0),
                float(e.get("longitude") or 0),
                e.get("date") or "",
                e.get("description") or "",
                e.get("wikipedia_title") or (e.get("label_ja", "") if re.fullmatch(r"Q[1-9][0-9]*", qid) else ""),
                dump(e.get("venue")),
                dump(e.get("occurrences")),
                dump(e.get("annual_schedule")),
                dump(e.get("cultural_relaw")),
                e.get("description_source") or "",
                e.get("coordinate_source") or "",
                e.get("coordinate_prefecture") or "",
                e.get("coordinate_validation_source") or "",
                e.get("jalan_lrg_code") or "",
                e.get("jalan_lrg_name") or "",
                e.get("jalan_sml_code") or "",
                e.get("jalan_sml_name") or "",
                dump(e.get("lifecycle")),
            )
            columns = (
                "qid,label_ja,label_en,prefecture,latitude,longitude,"
                "date,description,wikipedia_title,venue_json,occurrences_json,"
                "annual_schedule_json,cultural_relaw_json,description_source,coordinate_source,"
                "coordinate_prefecture,coordinate_validation_source,"
                "jalan_lrg_code,jalan_lrg_name,jalan_sml_code,jalan_sml_name,lifecycle_json"
            ).split(",")
            if len(columns) != len(values):
                raise SystemExit(
                    f"column/value mismatch: {len(columns)} cols vs {len(values)} values"
                )
            placeholders = ",".join("?" * len(values))
            cur = conn.execute(
                f"INSERT INTO festival ({','.join(columns)}) VALUES ({placeholders})",
                values,
            )
            festival_id = cur.lastrowid
            for tag in (e.get("categories") or []):
                if tag not in type_ids:
                    c = conn.execute("INSERT INTO category_types (name) VALUES (?)", (tag,))
                    type_ids[tag] = c.lastrowid
                tag_total += 1
                conn.execute(
                    "INSERT INTO festival_categories (festival_id,type_id) VALUES (?,?)",
                    (festival_id, type_ids[tag]),
                )
        conn.commit()

        n_f = conn.execute("SELECT COUNT(*) FROM festival").fetchone()[0]
        n_type = conn.execute("SELECT COUNT(*) FROM category_types").fetchone()[0]
        n_link = conn.execute("SELECT COUNT(*) FROM festival_categories").fetchone()[0]
        n_tagged = conn.execute(
            "SELECT COUNT(DISTINCT festival_id) FROM festival_categories"
        ).fetchone()[0]
        print(
            f"festivals={n_f} category_types={n_type} links={n_link} "
            f"tagged={n_tagged} tag_assignments={tag_total}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    build()
