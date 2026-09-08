#!/usr/bin/env python3
"""Alert when the local Ollama proxy is unavailable or materially unhealthy.

This is intentionally a small, dependency-free oneshot.  It reads the proxy's
append-only usage log and probes the public local endpoint, so it catches both
upstream failures and the otherwise-successful ``/v1/models`` ``data: []``
failure mode.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROXY_URL = os.environ.get("OLLAMA_PROXY_MONITOR_URL", "http://localhost:11434")
USAGE_DIR = Path(os.environ.get(
    "OLLAMA_PROXY_USAGE_DIR", str(Path.home() / "data" / "ollama-proxy")))
STATE_FILE = Path(os.environ.get(
    "OLLAMA_PROXY_MONITOR_STATE", str(USAGE_DIR / "monitor-state.json")))
WINDOW = timedelta(hours=1)
REQUEST_TIMEOUT_SECONDS = 10
MIN_REQUESTS = 10
FAILURE_RATE = 0.20
MIN_FAILURES = 3
REMINDER = timedelta(minutes=30)
PATHS = frozenset({"/api/generate", "/v1/chat/completions"})
EXPECTED_QUEUE_BUSY = "generation queue busy"


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _months_in_window(cutoff: datetime, now: datetime) -> list[str]:
    """Return the one or two monthly log suffixes which can overlap a window."""
    cursor = cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    months: list[str] = []
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m"))
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return months


def read_usage(now: datetime) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Read only records in the rolling window; malformed records are skipped."""
    cutoff = now - WINDOW
    rows: list[dict[str, Any]] = []
    malformed = 0
    errors: list[str] = []
    for month in _months_in_window(cutoff, now):
        path = USAGE_DIR / f"usage-{month}.jsonl"
        if not path.exists():
            continue
        try:
            with path.open(encoding="utf-8") as fp:
                for line in fp:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
                        continue
                    if not isinstance(record, dict):
                        malformed += 1
                        continue
                    timestamp = _parse_ts(record.get("ts"))
                    if timestamp is None:
                        malformed += 1
                        continue
                    if timestamp >= cutoff and timestamp <= now and record.get("path") in PATHS:
                        rows.append(record)
        except OSError as exc:
            errors.append(f"usage log {path.name} cannot be read: {exc}")
    return rows, malformed, errors


def probe_models(opener=urllib.request.urlopen) -> tuple[int | None, str | None]:
    request = urllib.request.Request(f"{PROXY_URL.rstrip('/')}/v1/models")
    try:
        with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        return None, f"/v1/models probe failed: {exc}"
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None, "/v1/models response has no data array"
    return len(models), None


def summarize(rows: list[dict[str, Any]]) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Return eligible total, failures, and per-path (total, failures).

    A 503 created by this proxy's intentional one-at-a-time generation gate is
    not an upstream failure.  Its exact error marker is part of the proxy
    contract, so exclude it from both numerator and denominator.
    """
    total = failures = 0
    per_path = {path: [0, 0] for path in PATHS}
    for row in rows:
        path = row["path"]
        error = str(row.get("error") or "")
        status = row.get("status")
        if status == 503 and error == EXPECTED_QUEUE_BUSY:
            continue
        total += 1
        per_path[path][0] += 1
        failed = status != 200 or bool(error)
        if failed:
            failures += 1
            per_path[path][1] += 1
    return total, failures, {path: (values[0], values[1]) for path, values in per_path.items()}


def load_state() -> dict[str, Any]:
    try:
        with STATE_FILE.open(encoding="utf-8") as fp:
            state = json.load(fp)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        return {"state_error": str(exc)}
    return state if isinstance(state, dict) else {"state_error": "not an object"}


def save_state(state: dict[str, Any]) -> str | None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(STATE_FILE)
    except OSError as exc:
        return str(exc)
    return None


def _last_notification(state: dict[str, Any]) -> datetime | None:
    return _parse_ts(state.get("last_notification"))


def run(now: datetime | None = None, opener=urllib.request.urlopen) -> tuple[int, str]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    model_count, probe_error = probe_models(opener)
    rows, malformed, log_errors = read_usage(now)
    total, failures, per_path = summarize(rows)
    findings = list(log_errors)
    if probe_error:
        findings.append(probe_error)
    elif model_count == 0:
        findings.append("/v1/models returned data: []")

    if total >= MIN_REQUESTS and (failures >= MIN_FAILURES or failures / total >= FAILURE_RATE):
        findings.append(
            f"actionable proxy failures: {failures}/{total} ({failures / total:.1%}) in the last hour")

    details = ", ".join(
        f"{path}={failed}/{count}" for path, (count, failed) in sorted(per_path.items()))
    diagnostics = f"models={model_count if model_count is not None else 'unknown'}; {details}"
    if malformed:
        diagnostics += f"; skipped_malformed={malformed}"

    state = load_state()
    if state.get("state_error"):
        findings.append(f"monitor state cannot be read: {state['state_error']}")
    if not findings:
        error = save_state({"active": False, "checked_at": now.isoformat(timespec="seconds")})
        if error:
            return 1, f"ollama proxy monitor cannot save healthy state: {error}; {diagnostics}"
        return 3, f"ollama proxy monitor healthy: {diagnostics}"

    previous_notification = _last_notification(state)
    notify = not state.get("active") or previous_notification is None or now - previous_notification >= REMINDER
    next_state: dict[str, Any] = {
        "active": True,
        "checked_at": now.isoformat(timespec="seconds"),
        "findings": findings,
    }
    if notify:
        next_state["last_notification"] = now.isoformat(timespec="seconds")
    elif previous_notification is not None:
        next_state["last_notification"] = previous_notification.isoformat(timespec="seconds")
    error = save_state(next_state)
    if error:
        return 1, f"ollama proxy monitor cannot save alert state: {error}; {diagnostics}; " + "; ".join(findings)
    if notify:
        return 1, f"ollama proxy monitor ALERT: {diagnostics}; " + "; ".join(findings)
    return 3, f"ollama proxy monitor still unhealthy (notification suppressed): {diagnostics}; " + "; ".join(findings)


def main() -> int:
    code, message = run()
    print(message, file=sys.stderr if code == 1 else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
