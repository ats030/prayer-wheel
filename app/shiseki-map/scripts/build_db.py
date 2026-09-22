#!/usr/bin/env python3
"""frontend/shiseki.json を検索用 SQLite に変換する。"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "shiseki.json"
DST = ROOT / "frontend" / "shiseki.db"
SCHEMA = """
DROP TABLE IF EXISTS shiseki_categories; DROP TABLE IF EXISTS categories; DROP TABLE IF EXISTS shiseki;
CREATE TABLE shiseki (id INTEGER PRIMARY KEY, qid TEXT NOT NULL UNIQUE, label_ja TEXT NOT NULL,
label_en TEXT NOT NULL DEFAULT '', prefecture TEXT NOT NULL DEFAULT '', latitude REAL NOT NULL,
longitude REAL NOT NULL, description TEXT NOT NULL DEFAULT '', title_ja TEXT NOT NULL DEFAULT '',
era TEXT NOT NULL DEFAULT '', designation TEXT NOT NULL DEFAULT 'unknown',
designation_label TEXT NOT NULL DEFAULT '', designation_source TEXT NOT NULL DEFAULT '',
heritage_id TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
jalan_lrg_code TEXT NOT NULL DEFAULT '', jalan_lrg_name TEXT NOT NULL DEFAULT '',
jalan_sml_code TEXT NOT NULL DEFAULT '', jalan_sml_name TEXT NOT NULL DEFAULT '');
CREATE INDEX idx_shiseki_prefecture ON shiseki(prefecture);
CREATE INDEX idx_shiseki_designation ON shiseki(designation);
CREATE TABLE categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE shiseki_categories (shiseki_id INTEGER NOT NULL REFERENCES shiseki(id),
type_id INTEGER NOT NULL REFERENCES categories(id), PRIMARY KEY (shiseki_id, type_id));
"""
VALID_DESIGNATIONS = {"special", "national", "local", "undesig", "unknown"}

def build():
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    if DST.exists():
        DST.unlink()
    conn = sqlite3.connect(DST)
    try:
        conn.executescript(SCHEMA)
        category_ids = {}
        for item in rows:
            designation = item.get("designation", "unknown")
            if designation not in VALID_DESIGNATIONS:
                designation = "unknown"
            cur = conn.execute(
                "INSERT INTO shiseki (qid,label_ja,label_en,prefecture,latitude,longitude,description,title_ja,era,designation,designation_label,designation_source,heritage_id,source_url,jalan_lrg_code,jalan_lrg_name,jalan_sml_code,jalan_sml_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item["qid"], item["label_ja"], item.get("label_en", ""), item.get("prefecture", ""),
                 float(item["latitude"]), float(item["longitude"]), item.get("description", ""),
                 item.get("title_ja", ""), item.get("era", ""), designation,
                 item.get("designation_label", ""), item.get("designation_source", ""),
                 item.get("heritage_id", ""), item.get("source_url", ""),
                 item.get("jalan_lrg_code", ""), item.get("jalan_lrg_name", ""),
                 item.get("jalan_sml_code", ""), item.get("jalan_sml_name", "")),
            )
            for category in dict.fromkeys(item.get("categories") or ["その他"]):
                if category not in category_ids:
                    category_ids[category] = conn.execute("INSERT INTO categories(name) VALUES (?)", (category,)).lastrowid
                conn.execute("INSERT INTO shiseki_categories(shiseki_id,type_id) VALUES (?,?)", (cur.lastrowid, category_ids[category]))
        conn.commit()
        print(f"shiseki={len(rows)} categories={len(category_ids)}")
    finally:
        conn.close()

if __name__ == "__main__":
    build()
