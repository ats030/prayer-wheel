#!/usr/bin/env python3
"""Offline integrity check for committed Jalan LRG assignments."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATASETS = (
    ROOT / "app/onsen-map/frontend/onsen.json",
    ROOT / "app/omatsuri-map/frontend/festivals.json",
    ROOT / "app/shiseki-map/frontend/shiseki.json",
)
OVERRIDES = ROOT / "data/jalan-lrg-overrides.json"
SML_OVERRIDES = ROOT / "data/jalan-sml-overrides.json"


def main():
    overrides = json.loads(OVERRIDES.read_text())
    sml_overrides = json.loads(SML_OVERRIDES.read_text())
    errors = []
    total = 0
    record_qids = set()
    for path in DATASETS:
        records = json.loads(path.read_text())
        total += len(records)
        for record in records:
            qid = str(record.get("qid"))
            if qid in record_qids:
                errors.append(f"{path}:{qid}: duplicate qid across datasets")
            record_qids.add(qid)
            code = record.get("jalan_lrg_code", "")
            name = record.get("jalan_lrg_name", "")
            override = overrides.get(qid)
            if not re.fullmatch(r"\d{4}00", code):
                errors.append(f"{path}:{qid}: malformed or missing code {code!r}")
            if not name:
                errors.append(f"{path}:{qid}: missing name")
            if not override:
                errors.append(f"{path}:{qid}: missing override")
            elif (override.get("code"), override.get("name")) != (code, name):
                errors.append(f"{path}:{qid}: dataset and override differ")
            evidence = (override or {}).get("evidence", {})
            expected_url = f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/"
            if evidence.get("official_url") != expected_url:
                errors.append(f"{path}:{qid}: official URL mismatch")
            if not evidence.get("confirmed_at") or not evidence.get("method"):
                errors.append(f"{path}:{qid}: incomplete evidence")
            sml_code = record.get("jalan_sml_code", "")
            sml_name = record.get("jalan_sml_name", "")
            sml = sml_overrides.get(qid)
            if not re.fullmatch(r"\d{6}", sml_code) or sml_code.endswith("00"):
                errors.append(f"{path}:{qid}: malformed or missing SML code {sml_code!r}")
            if not sml or (sml.get("lrg_code"), sml.get("sml_code"), sml.get("sml_name")) != (code, sml_code, sml_name):
                errors.append(f"{path}:{qid}: dataset and SML override differ")
            sml_evidence = (sml or {}).get("evidence", {})
            sml_url = f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/SML_{sml_code}/"
            if sml_evidence.get("official_url") != sml_url:
                errors.append(f"{path}:{qid}: official SML URL mismatch")
            if not sml_evidence.get("confirmed_at") or not sml_evidence.get("method"):
                errors.append(f"{path}:{qid}: incomplete SML evidence")
    if errors:
        raise SystemExit("\n".join(errors[:100]))
    override_qids = set(overrides)
    if override_qids != record_qids:
        missing = sorted(record_qids - override_qids)
        stale = sorted(override_qids - record_qids)
        raise SystemExit(f"override keys differ: missing={missing[:20]} stale={stale[:20]}")
    if set(sml_overrides) != record_qids:
        raise SystemExit("SML override keys differ from dataset qids")
    print(json.dumps({"records": total, "lrg_overrides": len(overrides), "sml_overrides": len(sml_overrides), "unassigned": 0}))


if __name__ == "__main__":
    main()
