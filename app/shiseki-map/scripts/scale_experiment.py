#!/usr/bin/env python3
"""Build an offline provenance pilot and benchmark a 30k catalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import statistics
import time
from pathlib import Path

DEFAULT_REGIONS = ("北海道", "東京都", "沖縄県")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE ingestion_runs (
 id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, retrieved_at TEXT NOT NULL,
 source_url TEXT NOT NULL, license_status TEXT NOT NULL);
CREATE TABLE source_records (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
 source_id TEXT NOT NULL UNIQUE, raw_json TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
 publication_status TEXT NOT NULL, hold_reason TEXT NOT NULL DEFAULT '');
CREATE TABLE places (
 id INTEGER PRIMARY KEY, canonical_id TEXT NOT NULL UNIQUE, label_ja TEXT NOT NULL,
 prefecture TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
 layer TEXT NOT NULL, designation TEXT NOT NULL, description TEXT NOT NULL DEFAULT '');
CREATE TABLE place_sources (
 place_id INTEGER NOT NULL REFERENCES places(id),
 source_record_id INTEGER NOT NULL REFERENCES source_records(id),
 source_url TEXT NOT NULL, evidence_kind TEXT NOT NULL,
 PRIMARY KEY (place_id, source_record_id, source_url, evidence_kind));
CREATE TABLE external_ids (
 place_id INTEGER NOT NULL REFERENCES places(id), scheme TEXT NOT NULL,
 external_id TEXT NOT NULL, PRIMARY KEY (scheme, external_id));
CREATE TABLE review_queue (
 id INTEGER PRIMARY KEY, source_record_id INTEGER REFERENCES source_records(id),
 candidate_place_id INTEGER REFERENCES places(id), reason TEXT NOT NULL,
 details TEXT NOT NULL DEFAULT '');
CREATE INDEX places_prefecture_label ON places(prefecture, label_ja);
CREATE INDEX places_coordinates ON places(latitude, longitude);
"""


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　・·ー（）()]+", "", value).casefold()


def layer_for(row: dict) -> str:
    if row.get("designation") in {"special", "national", "local"}:
        return "designated_site"
    categories = set(row.get("categories") or [])
    if categories & {"遺跡", "古墳", "城跡", "史跡", "社寺・宗教遺跡"}:
        return "historical_heritage"
    return "historical_spot"


def hold_reason(row: dict) -> str:
    required = ("label_ja", "prefecture", "latitude", "longitude", "source_url")
    missing = [field for field in required if row.get(field) in (None, "")]
    if missing:
        return "missing:" + ",".join(missing)
    if not row.get("categories"):
        return "missing:categories"
    if not (-90 <= float(row["latitude"]) <= 90 and -180 <= float(row["longitude"]) <= 180):
        return "invalid:coordinates"
    return ""


def create_database(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    return connection


def ingest(connection: sqlite3.Connection, rows: list[dict], regions: tuple[str, ...]) -> dict:
    cursor = connection.execute(
        "INSERT INTO ingestion_runs(source_name,retrieved_at,source_url,license_status) VALUES(?,?,?,?)",
        ("wikidata_snapshot", "2026-09-23", "https://www.wikidata.org/", "approved"),
    )
    run_id = cursor.lastrowid
    selected = [row for row in rows if row.get("prefecture") in regions]
    holds = 0
    for row in selected:
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        reason = hold_reason(row)
        status = "hold" if reason else "publish"
        holds += bool(reason)
        source_id = ("wikidata:" + str(row["qid"])) if row.get("qid") else (
            "snapshot:" + hashlib.sha256(raw.encode()).hexdigest()[:20]
        )
        source_cursor = connection.execute(
            "INSERT INTO source_records(run_id,source_id,raw_json,raw_sha256,publication_status,hold_reason) VALUES(?,?,?,?,?,?)",
            (run_id, source_id, raw, hashlib.sha256(raw.encode()).hexdigest(), status, reason),
        )
        if reason:
            connection.execute(
                "INSERT INTO review_queue(source_record_id,reason,details) VALUES(?,?,?)",
                (source_cursor.lastrowid, reason, source_id),
            )
            continue
        place_cursor = connection.execute(
            "INSERT INTO places(canonical_id,label_ja,prefecture,latitude,longitude,layer,designation,description) VALUES(?,?,?,?,?,?,?,?)",
            (source_id, row["label_ja"], row["prefecture"], row["latitude"], row["longitude"],
             layer_for(row), row.get("designation", "unknown"), row.get("description", "")),
        )
        place_id = place_cursor.lastrowid
        connection.execute(
            "INSERT INTO place_sources VALUES(?,?,?,?)",
            (place_id, source_cursor.lastrowid, row["source_url"], "structured_metadata"),
        )
        designation_source = row.get("designation_source")
        if designation_source and designation_source != row["source_url"]:
            connection.execute(
                "INSERT INTO place_sources VALUES(?,?,?,?)",
                (place_id, source_cursor.lastrowid, designation_source, "designation"),
            )
        if row.get("qid"):
            connection.execute("INSERT INTO external_ids VALUES(?,?,?)", (place_id, "wikidata", row["qid"]))
    connection.commit()
    duplicates = flag_duplicate_candidates(connection)
    return {"selected": len(selected), "published": len(selected) - holds, "held": holds,
            "duplicate_candidates": duplicates}


def flag_duplicate_candidates(connection: sqlite3.Connection) -> int:
    rows = connection.execute(
        "SELECT id,label_ja,prefecture,latitude,longitude FROM places ORDER BY prefecture,label_ja"
    ).fetchall()
    groups: dict[tuple[str, str], list[tuple]] = {}
    for row in rows:
        groups.setdefault((row[2], normalize_name(row[1])), []).append(row)
    count = 0
    for matches in groups.values():
        if len(matches) < 2:
            continue
        for candidate in matches[1:]:
            connection.execute(
                "INSERT INTO review_queue(candidate_place_id,reason,details) VALUES(?,?,?)",
                (candidate[0], "possible_duplicate", f"same normalized name as place:{matches[0][0]}"),
            )
            count += 1
    connection.commit()
    return count


def benchmark(connection: sqlite3.Connection, target: int, repeats: int = 40) -> dict:
    base = connection.execute(
        "SELECT label_ja,prefecture,latitude,longitude,layer,designation,description FROM places"
    ).fetchall()
    if not base:
        raise ValueError("pilot has no publishable rows")
    connection.execute("CREATE TABLE benchmark_places AS SELECT * FROM places WHERE 0")
    payload = []
    for index in range(target):
        row = base[index % len(base)]
        payload.append((f"benchmark:{index}",) + row)
    connection.executemany(
        "INSERT INTO benchmark_places(canonical_id,label_ja,prefecture,latitude,longitude,layer,designation,description) VALUES(?,?,?,?,?,?,?,?)",
        payload,
    )
    connection.execute("CREATE INDEX benchmark_pref_label ON benchmark_places(prefecture,label_ja)")
    connection.execute("CREATE INDEX benchmark_coords ON benchmark_places(latitude,longitude)")
    connection.commit()
    queries = {
        "prefecture_page": ("SELECT * FROM benchmark_places WHERE prefecture=? ORDER BY label_ja LIMIT 50", (DEFAULT_REGIONS[1],)),
        "viewport": ("SELECT canonical_id,label_ja,latitude,longitude,layer FROM benchmark_places WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? LIMIT 1000", (34.0, 36.5, 138.0, 141.0)),
        "keyword": ("SELECT canonical_id,label_ja,prefecture FROM benchmark_places WHERE prefecture=? AND label_ja LIKE ? ORDER BY label_ja LIMIT 50", (DEFAULT_REGIONS[1], "%城%")),
    }
    result = {}
    for name, (query, args) in queries.items():
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            connection.execute(query, args).fetchall()
            samples.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples)
        result[name] = {"median_ms": round(statistics.median(samples), 3),
                        "p95_ms": round(ordered[int(len(ordered) * 0.95) - 1], 3)}
    return result


def run(input_path: Path, output_path: Path, regions: tuple[str, ...], target: int) -> dict:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("output must not overwrite the source snapshot")
    if target < 1:
        raise ValueError("target must be positive")
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    connection = create_database(output_path)
    try:
        pilot = ingest(connection, rows, regions)
        performance = benchmark(connection, target)
        layers = dict(connection.execute("SELECT layer,COUNT(*) FROM places GROUP BY layer").fetchall())
        return {"regions": list(regions), "pilot": pilot, "layers": layers,
                "benchmark_records": target, "query_performance": performance,
                "supply_verdict": "unproven",
                "supply_reason": "The pilot validates the schema, not a reusable source capable of supplying 30,000 records."}
    finally:
        connection.close()


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=root / "frontend" / "shiseki.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regions", nargs="+", default=DEFAULT_REGIONS)
    parser.add_argument("--target", type=int, default=30_000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = run(args.input, args.output, tuple(args.regions), args.target)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
