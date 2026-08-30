#!/usr/bin/env python3
"""opencode の直近 compaction 要約を読み、「現在の依頼」節が入っているか確認する。

使い方: python3 scripts/opencode-check-compaction.py [表示件数]
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DB = Path.home() / ".local/share/opencode/opencode.db"
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3

with tempfile.TemporaryDirectory() as tmp:
    copy = Path(tmp) / "oc.db"
    shutil.copy2(DB, copy)
    for suffix in ("-wal", "-shm"):
        src = DB.with_name(DB.name + suffix)
        if src.exists():
            shutil.copy2(src, copy.with_name(copy.name + suffix))
    con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT id, session_id, data FROM message ORDER BY id DESC LIMIT 4000"
    ).fetchall()

found = 0
for mid, sid, data in rows:
    try:
        d = json.loads(data)
    except (TypeError, ValueError):
        continue
    if not d.get("summary"):
        continue
    body = json.dumps(d, ensure_ascii=False)
    ok = "現在の依頼" in body
    print(f"[{'OK ' if ok else 'NG '}] {sid} {mid}")
    found += 1
    if found >= limit:
        break

if found == 0:
    print("compaction 要約メッセージが見つからない。まだ発火していない可能性がある。")
