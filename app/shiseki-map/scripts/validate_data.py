#!/usr/bin/env python3
"""shiseki.json の公開前不変条件を検証する。"""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "frontend" / "shiseki.json"
rows = json.loads(path.read_text(encoding="utf-8"))
assert rows, "dataset is empty"
qids = [row["qid"] for row in rows]
assert len(qids) == len(set(qids)), "duplicate qid"
valid = {"special", "national", "local", "undesig", "unknown"}
for row in rows:
    assert row.get("label_ja"), row["qid"]
    assert -90 <= float(row["latitude"]) <= 90, row["qid"]
    assert -180 <= float(row["longitude"]) <= 180, row["qid"]
    assert row.get("designation") in valid, row["qid"]
    assert row.get("designation_source"), row["qid"]
    assert row.get("source_url"), row["qid"]
    assert row.get("categories"), row["qid"]
print(f"validated {len(rows)} records")
