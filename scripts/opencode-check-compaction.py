#!/usr/bin/env python3
"""opencode の compaction 要約を読み、「現在の依頼」節が入っているか確認する。

要約は role=assistant / agent=compaction のメッセージで、本文は part テーブルにある。
role=user のメッセージにも summary={"diffs": []} が入るため、summary の真偽だけでは
絞り込めない。

使い方: python3 scripts/opencode-check-compaction.py [表示件数] [--since YYYY-MM-DD[ HH:MM]]
終了コード: 全件 OK なら 0、NG があれば 1、要約が見つからなければ 3。
"""
import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

DB = Path.home() / ".local/share/opencode/opencode.db"
ANCHOR = "現在の依頼"

ap = argparse.ArgumentParser()
ap.add_argument("limit", nargs="?", type=int, default=10)
ap.add_argument("--since", help="この日時以降の要約だけを見る (ローカル時刻)")
ap.add_argument("--show", action="store_true", help="NG の要約本文を表示する")
args = ap.parse_args()

since = None
if args.since:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            since = dt.datetime.strptime(args.since, fmt)
            break
        except ValueError:
            continue
    if since is None:
        sys.exit(f"--since を解釈できない: {args.since}")

with tempfile.TemporaryDirectory() as tmp:
    copy = Path(tmp) / "oc.db"
    shutil.copy2(DB, copy)
    for suffix in ("-wal", "-shm"):
        src = DB.with_name(DB.name + suffix)
        if src.exists():
            shutil.copy2(src, copy.with_name(copy.name + suffix))
    con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)

    rows = con.execute(
        "SELECT id, session_id, data FROM message ORDER BY time_created DESC LIMIT 8000"
    ).fetchall()

    found = ok = 0
    for mid, sid, data in rows:
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            continue
        if d.get("role") != "assistant":
            continue
        if d.get("agent") != "compaction" and d.get("mode") != "compaction":
            continue
        created = d.get("time", {}).get("created")
        when = dt.datetime.fromtimestamp(created / 1000) if created else None
        if since and when and when < since:
            break
        text = "".join(
            p.get("text", "")
            for p in (
                json.loads(r[0])
                for r in con.execute(
                    "SELECT data FROM part WHERE message_id=? ORDER BY id", (mid,)
                )
            )
            if p.get("type") == "text"
        )
        hit = ANCHOR in text
        ok += hit
        found += 1
        stamp = when.strftime("%Y-%m-%d %H:%M:%S") if when else "?"
        print(f"[{'OK ' if hit else 'NG '}] {stamp} {sid} {len(text)}字")
        if args.show and not hit:
            print(text[:800])
        if found >= args.limit:
            break

if found == 0:
    print("compaction 要約が見つからない。まだ発火していない可能性がある。")
    sys.exit(3)

print(f"\n{ok}/{found} 件に「{ANCHOR}」節あり")
sys.exit(0 if ok == found else 1)
