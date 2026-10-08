"""Measure real CPU for operator-only, non-AI requests; discard all private logs."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import secrets
import signal
import subprocess
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
from check import NoRedirect

HERE = Path(__file__).resolve().parent
ORIGIN = "https://ikimono-note-preview.ats030.workers.dev"
PATHS = ("/health", "/api/me", "/assets/index.js", "/vendor/photo/libheif.mjs")

def successful(row):
    cpu = row.get("cpu_ms")
    return bool(row.get("version") and row.get("status") == 200 and row.get("outcome") == "ok"
                and type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0)


def valid_isolate(row):
    identifier = row.get("isolate_id", "")
    try:
        parsed = uuid.UUID(identifier)
    except (ValueError, TypeError, AttributeError):
        return False
    return (str(parsed) == identifier and parsed.version == 4
            and type(row.get("isolate_invocation")) is int and row["isolate_invocation"] > 0)


def valid_sequence(rows):
    observed = {}
    for row in rows:
        if not valid_isolate(row):
            return False
        identifier, invocation = row["isolate_id"], row["isolate_invocation"]
        if invocation <= observed.get(identifier, 0):
            return False
        observed[identifier] = invocation
    return True


def measure(samples):
    started = datetime.now(timezone.utc).isoformat()
    state = json.loads((Path.home() / ".local/state/ikimono-cloudflare-preview/secrets.json").read_text())
    credential = "Basic " + base64.b64encode(
        ("preview:" + state["IKIMONO_PREVIEW_PASSWORD"]).encode()).decode()
    marker = secrets.token_hex(4)
    events = queue.Queue()
    process = subprocess.Popen(
        ["python3", str(HERE / "run_wrangler.py"), "tail", "--format", "json",
         "--header", "X-Ikimono-CPU-Probe:" + marker], cwd=HERE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)

    def read_events():
        buffer = ""
        decoder = json.JSONDecoder()
        for line in process.stdout:
            if not buffer and not line.lstrip().startswith("{"):
                continue  # Never emit raw CLI output or request headers.
            buffer += line
            try:
                event, end = decoder.raw_decode(buffer.lstrip())
            except json.JSONDecodeError:
                continue
            buffer = buffer.lstrip()[end:].strip()
            if not isinstance(event, dict):
                continue
            request = (event.get("event") or {}).get("request") or {}
            url = urlsplit(request.get("url", ""))
            query = parse_qs(url.query)
            # The server-side header filter isolates this run. CLI log
            # sanitization can transform opaque query markers; numeric sample
            # IDs and the allowlisted route are the correlation fields.
            sample = query.get("sample", [""])[0]
            if url.path not in PATHS or not (sample.isdigit() or sample in {"-1", "-2", "-3", "-4", "-5"}):
                continue
            # Reduce the event immediately: never retain credentials, logs,
            # cookies, client addresses, full exception traces, or arbitrary URLs.
            exceptions = []
            for error in event.get("exceptions") or []:
                lines = str(error.get("message", "")).splitlines()
                summary = lines[-1] if lines else ""
                for value in [credential, *state.values()]:
                    if isinstance(value, str) and value:
                        summary = summary.replace(value, "[redacted]")
                exceptions.append({"name": error.get("name"), "summary": summary[:200]})
            events.put({"sample": sample, "path": url.path, "exceptions": exceptions,
                        "cpu_ms": event.get("cpuTime"), "wall_ms": event.get("wallTime"),
                        "outcome": event.get("outcome"),
                        "version": (event.get("scriptVersion") or {}).get("id")})

    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    requests = {}
    def fetch(path, sample):
        request = Request(ORIGIN + path + "?cpu_check=" + marker + "&sample=" + sample,
                          headers={"Authorization": credential, "User-Agent": "ikimono-cpu-check/1.0",
                                   "X-Ikimono-CPU-Probe": marker})
        try:
            response = build_opener(NoRedirect).open(request, timeout=30)
        except HTTPError as error:
            response = error
        except (URLError, OSError) as error:
            return {"status": None, "bytes": 0, "sha256": None, "network_error": type(error).__name__}
        try:
            with response:
                body = response.read()
                invocation = response.headers.get("X-Preview-Isolate-Invocation", "")
                return {"status": response.status, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "isolate_id": response.headers.get("X-Preview-Isolate", ""),
                        "isolate_invocation": int(invocation) if invocation.isdigit() else None}
        except OSError as error:
            return {"status": None, "bytes": 0, "sha256": None, "network_error": type(error).__name__}
    try:
        time.sleep(5)  # Give the tail subscription time to attach.
        if process.poll() is not None:
            raise RuntimeError("Tail subscription failed; raw output withheld")
        # CLI startup is not proof of an attached websocket. Confirm an actual
        # tagged event before collecting the complete comparison sample set.
        subscription_probe = None
        for attempt in range(5):
            probe_sample = str(-1 - attempt)
            probe_response = fetch("/health", probe_sample)
            readiness_deadline = time.monotonic() + 3
            while time.monotonic() < readiness_deadline:
                try:
                    event = events.get(timeout=max(0.001, readiness_deadline - time.monotonic()))
                except queue.Empty:
                    break
                if event["sample"] == probe_sample:
                    subscription_probe = {**event, **probe_response}
                    break
            if subscription_probe is not None:
                break
        else:
            raise RuntimeError("Tail did not confirm the subscription")
        for path in PATHS:
            for turn in range(samples + 1):
                sample = str(len(requests))
                requests[sample] = {"path": path, "turn": turn, **fetch(path, sample)}
                time.sleep(1)
        records = {}
        deadline = time.monotonic() + 40
        while len(records) < len(requests) and time.monotonic() < deadline:
            try:
                event = events.get(timeout=1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            sample = event.pop("sample")
            if sample in requests:
                if event["path"] != requests[sample]["path"]:
                    raise RuntimeError("Mismatched measurement path")
                records[sample] = {**requests[sample], **event}
        complete = len(records) == len(requests)
        paired = [records.get(str(i), {**requests[str(i)], "cpu_ms": None,
                  "wall_ms": None, "outcome": "tail_not_observed", "version": None})
                  for i in range(len(requests))]
        eligible = complete and len({r["version"] for r in paired} | {
            subscription_probe["version"]}) == 1 and successful(subscription_probe) and all(
                successful(r) for r in paired) and valid_sequence([subscription_probe, *paired])
        return {"origin": ORIGIN, "cpu_unit": "milliseconds",
                "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "expected_records": len(requests), "observed_records": len(records),
                "complete": complete, "eligible_for_success_cpu_comparison": eligible,
                "first_request_per_route_excluded_from_subsequent_summary": True,
                "subscription_probe": subscription_probe,
                "records": paired}
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 5:
        parser.error("Use 1 to 5 subsequent samples per route")
    try:
        result = measure(args.samples)
    except (RuntimeError, OSError) as error:
        result = {"complete": False, "eligible_for_success_cpu_comparison": False,
                  "failure_type": type(error).__name__, "records": []}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["eligible_for_success_cpu_comparison"]:
        print("FAIL: incomplete, unsuccessful, or invalid CPU evidence; diagnostic JSON written")
        raise SystemExit(2)
    for path in PATHS:
        rows = [r for r in result["records"] if r["path"] == path and r["turn"] > 0]
        print(path, "subsequent CPU ms/isolate/invocation:",
              [(r["cpu_ms"], r["isolate_id"], r["isolate_invocation"]) for r in rows])
