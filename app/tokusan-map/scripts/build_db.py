#!/usr/bin/env python3
"""frontend/tokusan.json を検索用 SQLite (frontend/tokusan.db) に変換する。"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "tokusan.json"
DST = ROOT / "frontend" / "tokusan.db"
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
  source_url TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_tokusan_prefecture ON tokusan(prefecture);
"""


def main():
    if not SRC.exists():
        raise SystemExit(f"入力ファイルが見つからない: {SRC}")
    rows = json.loads(SRC.read_text(encoding="utf-8"))
    con = sqlite3.connect(DST)
    con.executescript(SCHEMA)
    for r in rows:
        con.execute(
            "INSERT INTO tokusan (qid, label_ja, label_en, place, prefecture,"
            " city, lat, lng, evidence, confidence, source_url)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.get("qid", ""),
                r.get("label_ja", ""),
                r.get("label_en", ""),
                r.get("place", ""),
                r.get("prefecture", ""),
                r.get("city", ""),
                float(r.get("lat") or 0),
                float(r.get("lng") or 0),
                r.get("evidence", ""),
                float(r.get("confidence") or 0),
                r.get("source_url", ""),
            ),
        )
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM tokusan").fetchone()[0]
    pref = con.execute(
        "SELECT COUNT(*) FROM tokusan WHERE prefecture != ''"
    ).fetchone()[0]
    con.close()
    print(f"tokusan.db: 品目 {count} 件 (都道府県特定済み {pref} 件) -> {DST}")


if __name__ == "__main__":
    main()
