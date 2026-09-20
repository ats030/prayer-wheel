#!/usr/bin/env python3
"""Render the local Ollama proxy state for one tmux status segment."""

from __future__ import annotations

import json
import urllib.request

STATUS_URL = "http://127.0.0.1:11434/api/opencode-status"


def duration(seconds: int) -> str:
    minutes, seconds = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def render(data: dict) -> str:
    state = data.get("state")
    if state == "idle":
        return "LLM アイドル"
    label = "待機中" if state == "queued" else "生成中"
    model = data.get("model") or "不明"
    elapsed = duration(int(data.get("elapsed_seconds") or 0))
    queued = int(data.get("queue_depth") or 0)
    last = data.get("last_received_seconds")
    received = "--" if last is None else f"{int(last)}秒前"
    return f"{label} {elapsed}｜{model}｜待ち {queued}｜受信 {received}"


def main() -> None:
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=0.4) as response:
            print(render(json.load(response)))
    except (OSError, ValueError):
        print("LLM 状態取得不可")


if __name__ == "__main__":
    main()
