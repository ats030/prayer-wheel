#!/usr/bin/env python3
"""Check that `bd import <jsonl>` actually applied every field (ats030-konc).

With bd 1.0.3, importing a row for an issue that already exists overwrites
fields such as title and updated_at but keeps the DB's defer_until, so a
defer date changed in a merged .beads/issues.jsonl is silently dropped.
Run this right after the import:

    uv run python scripts/bd-import-verify.py .beads/issues.jsonl

It exports the live DB to a temporary file and lists every issue field that
differs from the given jsonl. Comment ids are ignored. Exit status is 1 when
any difference is found; fix those with bd update/bd defer, then rerun.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def load(path):
    rows = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "id" not in row:
            continue  # memories and other non-issue records
        for comment in row.get("comments") or []:
            comment.pop("id", None)
        rows[row["id"]] = row
    return rows


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: bd-import-verify.py <imported.jsonl>")
    expected = load(sys.argv[1])
    with tempfile.NamedTemporaryFile(suffix=".jsonl") as tmp:
        subprocess.run(["bd", "export", "-o", tmp.name], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        actual = load(tmp.name)
    diffs = []
    for issue_id, want in sorted(expected.items()):
        got = actual.get(issue_id)
        if got is None:
            diffs.append(f"{issue_id}: missing from DB")
            continue
        for key in sorted(set(want) | set(got)):
            if want.get(key) != got.get(key):
                diffs.append(f"{issue_id}.{key}: jsonl={want.get(key)!r} db={got.get(key)!r}")
    for line in diffs:
        print(line)
    print(json.dumps({"issues": len(expected), "differences": len(diffs)}))
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
