#!/usr/bin/env python3
"""Seed private generation caches without changing either app's live data.

Run after gracefully stopping legacy warmers. Existing work keys win; imported
sources and their hashes are preserved for rollback and provenance.
"""
import hashlib
import json
import os
import fcntl
from pathlib import Path
import tempfile
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "data/summary-work"


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".import-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        import_caches()


def import_caches():
    imports = []
    # Validate all inputs before writing any cache. Do not import progress from
    # legacy logs: their OK counters include failed generation and empty output.
    for kind in ("shiseki", "omatsuri", "onsen", "tokusan"):
        files = ["summaries.json"]
        if kind == "tokusan":
            files.append("official_summaries.json")
        for filename in files:
            sources = [ROOT.parent / f"{kind}-map/data" / filename,
                       ROOT / "data" / kind / filename]
            target = WORK / "cache" / kind / filename
            values = []
            for path in [*sources, target]:
                if path == target and not path.exists():
                    values.append({})
                    continue
                raw = path.read_bytes()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError(f"not a cache object: {path}")
                values.append(value)
            merged = {}
            for value in values:
                if filename == "official_summaries.json":
                    for qid, entry in value.items():
                        sections = merged.setdefault(qid, {"sections": {}})["sections"]
                        sections.update(entry.get("sections", {}))
                else:
                    merged.update(value)
            imports.append((kind, filename, sources, target, merged))
    # Establish a legacy baseline only when both official databases are exact
    # copies. This permits reuse at migration and invalidation on later edits;
    # it does not reconstruct the unknown historical generation revision.
    old_db = ROOT.parent / "tokusan-map/frontend/tokusan.db"
    new_db = ROOT / "data/tokusan/tokusan.db"
    if old_db.read_bytes() == new_db.read_bytes():
        with sqlite3.connect(f"file:{new_db}?mode=ro", uri=True) as db:
            rows = list(db.execute("SELECT qid, history, production FROM tokusan"))
        official = next(value for kind, name, _, _, value in imports
                        if kind == "tokusan" and name == "official_summaries.json")
        wiki = next(value for kind, name, _, _, value in imports
                    if kind == "tokusan" and name == "summaries.json")
        for qid, history, production in rows:
            for key, text in (("history", history), ("production", production)):
                if key in official.get(qid, {}).get("sections", {}) and text is not None:
                    marker = f"midokoro-official-source-v1:{qid}:{key}"
                    wiki.setdefault(marker, hashlib.sha256(text.encode()).hexdigest())
    manifest = []
    for kind, filename, sources, target, merged in imports:
        for path in sources:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            backup = WORK / "imports" / kind / f"{digest}-{filename}"
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(raw)
            manifest.append({"source": str(path.relative_to(ROOT.parent)),
                             "sha256": digest, "entries": len(json.loads(raw))})
        atomic_json(target, merged)
        print(f"{kind}/{filename}: merged={len(merged)}")
    atomic_json(WORK / "import-manifest.json", manifest)


if __name__ == "__main__":
    main()
