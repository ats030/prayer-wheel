#!/usr/bin/env python3
"""Self-test for the tmux status renderer; no live proxy is required."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).with_name("opencode-tmux-status.py")
spec = importlib.util.spec_from_file_location("opencode_tmux_status", SCRIPT)
status = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(status)

assert status.duration(5) == "00:05"
assert status.duration(65) == "01:05"
assert status.duration(3665) == "1:01:05"
assert status.render({"state": "idle"}) == "LLM アイドル"
assert status.render({
    "state": "queued", "model": "qwen3.8:27b", "elapsed_seconds": 62,
    "queue_depth": 2, "last_received_seconds": None,
}) == "待機中 01:02｜qwen3.8:27b｜待ち 2｜受信 --"
assert status.render({
    "state": "generating", "model": "qwen3.8:27b", "elapsed_seconds": 5,
    "queue_depth": 0, "last_received_seconds": 3,
}) == "生成中 00:05｜qwen3.8:27b｜待ち 0｜受信 3秒前"
print("opencode tmux status self-test: ok")
