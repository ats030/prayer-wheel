#!/usr/bin/env python3
"""Private serial worker, independent of the public server's write caches."""
import os
import sys
import fcntl
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.chdir(root)
work = root / "data/summary-work"
work.mkdir(parents=True, exist_ok=True)
lock = (work / "worker.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.set_inheritable(lock.fileno(), True)
env_file = Path.home() / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key == "OLLAMA_MODEL":
            os.environ.setdefault(key, value.strip().strip("\"'"))
os.environ["OFFICIAL_SUMMARY_PATH"] = str(work / "cache/tokusan/official_summaries.json")
os.environ["MIDOKORO_DATA_DIR"] = str(root / "data/summary-work/cache")
for kind in ("SHISEKI", "ONSEN", "OMATSURI", "TOKUSAN"):
    os.environ.pop(f"{kind}_SUMMARY_DISABLE", None)
    os.environ[f"{kind}_CACHE_MAX"] = "200000"
os.environ["SUMMARY_CACHE_MAX"] = "200000"
os.execv(str(root / "summary-worker"), ["summary-worker", "--kinds",
         "tokusan,onsen,omatsuri,shiseki", "--limit", "100", *sys.argv[1:]])
