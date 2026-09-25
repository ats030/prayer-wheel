#!/usr/bin/env python3
"""Self-test for ollama-proxy-monitor.py; uses no live proxy or usage logs."""

from __future__ import annotations

import importlib.util
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "ollama_proxy_monitor", Path(__file__).with_name("ollama-proxy-monitor.py"))
assert spec and spec.loader
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self, *unused):
        return json.dumps(self.payload).encode()


def models(count=1):
    return lambda request, timeout: Response({"data": [{"id": str(i)} for i in range(count)]})


def write_rows(directory, rows, month="2026-09"):
    (directory / f"usage-{month}.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def row(minutes, *, path="/api/generate", status=200, error=""):
    result = {"ts": (NOW - timedelta(minutes=minutes)).isoformat(), "path": path, "status": status}
    if error:
        result["error"] = error
    return result


def check(name, actual, expected):
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    monitor.USAGE_DIR = root
    monitor.STATE_FILE = root / "monitor-state.json"

    print("1. ログがなくモデル一覧が正常なら通知しない")
    code, message = monitor.run(NOW, models(2))
    check("exit", code, 3)
    check("healthy", "healthy" in message, True)

    print("2. キュー満杯503だけは上流障害として数えない")
    write_rows(root, [row(i, status=503, error="generation queue busy") for i in range(12)])
    code, message = monitor.run(NOW, models())
    check("exit", code, 3)
    check("eligible", "/api/generate=0/0" in message, True)

    print("3. 過去障害相当の非200率は通知する")
    write_rows(root, [row(i, status=503, error="HTTP 503") for i in range(9)] + [row(20 + i) for i in range(3)])
    code, message = monitor.run(NOW, models())
    check("exit", code, 1)
    check("rate", "9/12 (75.0%)" in message, True)

    print("4. 継続障害は30分まで通知を抑える")
    code, message = monitor.run(NOW + timedelta(minutes=5), models())
    check("exit", code, 3)
    check("suppressed", "notification suppressed" in message, True)
    code, message = monitor.run(NOW + timedelta(minutes=31), models())
    check("reminder exit", code, 1)

    print("5. 200でもerror付き応答は障害として数える")
    write_rows(root, [row(i, path="/v1/chat/completions", error="IncompleteRead(0 bytes read)") for i in range(3)] +
                    [row(20 + i, path="/v1/chat/completions") for i in range(9)])
    monitor.STATE_FILE.unlink()
    code, message = monitor.run(NOW, models())
    check("exit", code, 1)
    check("error rate", "3/12 (25.0%)" in message, True)

    print("5b. クライアント切断と対話キュー満杯は通知せず、切断数だけ出す")
    write_rows(root, [row(i, path="/v1/chat/completions", error="ConnectionResetError: [Errno 104] Connection reset by peer")
                      for i in range(5)] +
                     [row(10 + i, status=503, error="BrokenPipeError: [Errno 32] Broken pipe") for i in range(3)] +
                     [row(20 + i, path="/v1/chat/completions", status=503, error="interactive queue busy")
                      for i in range(5)] +
                     [row(30 + i, path="/v1/chat/completions") for i in range(10)])
    monitor.STATE_FILE.unlink()
    code, message = monitor.run(NOW, models())
    check("exit", code, 3)
    check("eligible", "/v1/chat/completions=0/10" in message, True)
    check("disconnects", "client_disconnects=8" in message, True)

    print("6. data: [] を通知する")
    write_rows(root, [])
    monitor.STATE_FILE.unlink()
    code, message = monitor.run(NOW, models(0))
    check("exit", code, 1)
    check("empty models", "data: []" in message, True)

    print("7. 壊れたログはスキップし、月境界の有効行を集計する")
    (root / "usage-2026-09.jsonl").write_text("not json\n" + json.dumps(row(1)) + "\n", encoding="utf-8")
    august = {"ts": (NOW - timedelta(days=8)).isoformat(), "path": "/api/generate", "status": 500}
    write_rows(root, [august], "2026-08")
    monitor.STATE_FILE.unlink()
    code, message = monitor.run(NOW, models())
    check("exit", code, 3)
    check("malformed", "skipped_malformed=1" in message, True)

print("ok")
