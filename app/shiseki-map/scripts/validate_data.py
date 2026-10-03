#!/usr/bin/env python3
"""shiseki.json の公開前不変条件を検証する。"""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "frontend" / "shiseki.json"
rows = json.loads(path.read_text(encoding="utf-8"))
assert rows, "dataset is empty"
ids = [row.get("id") or row.get("qid") for row in rows]
assert all(ids), "missing site ID"
assert len(ids) == len(set(ids)), "duplicate site ID"
qids = [row.get("qid") for row in rows if row.get("qid")]
assert len(qids) == len(set(qids)), "duplicate Wikidata QID"
valid = {"special", "national", "local", "undesig", "unknown"}
for row in rows:
    site_id = row.get("id") or row.get("qid")
    assert row.get("label_ja"), site_id
    assert -90 <= float(row["latitude"]) <= 90, site_id
    assert -180 <= float(row["longitude"]) <= 180, site_id
    assert row.get("designation") in valid, site_id
    assert row.get("designation_source"), site_id
    assert row.get("source_url"), site_id
    assert row.get("categories"), site_id
    if not row.get("qid"):
        assert row.get("id", "").startswith(("tokyo:", "bunka:")), site_id
        assert row.get("source_name") and row.get("source_license"), site_id
        if row["id"].startswith("tokyo:"):
            assert row.get("visit_url") and row.get("access_note"), site_id
print(f"validated {len(rows)} records")
