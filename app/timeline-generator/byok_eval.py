"""Explicit one-case comparison. Hidden key input; never resumes paid work."""
import argparse
from decimal import Decimal, InvalidOperation
import getpass
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from byok import MODEL, MODEL_STAGES, MIN_CALL_INTERVAL, INPUT_TOKENS_PER_MINUTE, validate_key
from byok_pipeline import FetchBudget, bounded_byok
from byok_metrics import MaterialMetrics
from byok_runtime import ByokLimits
from public_security import result_view

ROOT = Path(__file__).resolve().parent
HASHED = ("timeline.py", "milestones.py", "byok.py", "byok_pipeline.py", "byok_metrics.py", "byok_eval.py",
          "quality_eval.py", "quality_gold.json", "quality_holdout.json")


def operator_child(query, unused_key, options, connection):
    """Explicit internal comparison only; never selected by a BYOK receipt."""
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_microusd": 0,
             "max_cost_microusd": 0, "cost_is_upper_bound": False,
             "calls_by_stage": {}, "request_bytes_by_stage": {}}
    send_lock, usage_lock = threading.Lock(), threading.Lock()
    metrics = None
    def emit(record):
        with send_lock:
            connection.send(record)
    try:
        os.environ["TIMELINE_SOURCE"] = "wikipedia"
        import timeline
        metrics = MaterialMetrics(timeline)
        budget = FetchBudget(options["fetch_calls"], options["fetch_bytes"])
        original = timeline.json_request
        def request(url, payload=None, timeout=20):
            if url != timeline.OLLAMA_URL + "/api/chat" or payload is None:
                return budget.json(url, payload, timeout)
            with usage_lock:
                usage["calls"] += 1
                stage = MODEL_STAGES.get(frozenset(payload.get("format", {}).get("properties", {})), "other")
                usage["calls_by_stage"][stage] = usage["calls_by_stage"].get(stage, 0) + 1
                usage["request_bytes_by_stage"][stage] = usage["request_bytes_by_stage"].get(stage, 0) + len(
                    json.dumps(payload, ensure_ascii=False).encode())
                emit({"kind": "usage", "usage": json.loads(json.dumps(usage)), "material": metrics.summary()})
            response = original(url, payload, timeout)
            with usage_lock:
                for field, source in (("input_tokens", "prompt_eval_count"), ("output_tokens", "eval_count")):
                    count = response.get(source) if isinstance(response, dict) else None
                    if type(count) is int and count >= 0:
                        usage[field] += count
                    else:
                        usage["cost_is_upper_bound"] = True
                emit({"kind": "usage", "usage": json.loads(json.dumps(usage)), "material": metrics.summary()})
            return response
        timeline.json_request = request
        article = timeline.WebReader.request
        timeline.WebReader.request = lambda reader, url, limit=2_000_000: budget.article(article, reader, url, limit)
        emit(timeline.build_timeline(timeline.parse_query(query), emit))
    except Exception:
        emit({"kind": "error", "error": "processing_error"})
    finally:
        emit({"kind": "usage", "usage": usage, "material": metrics.summary() if metrics else {}})
        connection.close()


def configuration(time_limit, max_cost, model_calls=60):
    # Experiment values are explicit, not production defaults or measured limits.
    limits = ByokLimits(concurrent=1, starts=1, owners=1, receipts=1, ttl=time_limit,
        time_limit=time_limit, fetch_calls=100, fetch_bytes=40_000_000,
        model_calls=model_calls, input_bytes=100_000, output_tokens=6000, max_cost_microusd=max_cost)
    return {**vars(limits), "model_min_call_interval_seconds": MIN_CALL_INTERVAL,
            "model_input_tokens_per_minute": INPUT_TOKENS_PER_MINUTE}


def measure(theme, route, key, options):
    records, stopped = [], threading.Event()
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in HASHED}
    start = time.monotonic()
    try:
        if route == "byok":
            bounded_byok(theme, key, options, records.append, stopped)
        else:
            bounded_byok(theme, None, options, records.append, stopped, child=operator_child)
    except KeyboardInterrupt:
        stopped.set()
    finally:
        key = None
    result = next((r for r in records if r.get("kind") == "result"), None)
    usage = next((r["usage"] for r in reversed(records) if r.get("kind") == "usage"), None)
    material = next((r["material"] for r in reversed(records) if "material" in r), {})
    error = next((r["error"] for r in reversed(records) if r.get("kind") == "ended"), "cancelled")
    # quality_eval imports timeline. Keep it out of the spawn entry module so
    # each child can select Wikipedia before timeline reads its environment.
    from quality_eval import evaluate_result
    golds = [json.loads((ROOT / name).read_text()) for name in ("quality_gold.json", "quality_holdout.json")]
    gold = next(g for g in golds if theme in g["themes"])
    quality = evaluate_result(gold, result, theme)
    changed = any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest
                  for name, digest in hashes.items())
    passed = bool(result and quality.get("recall") == 1 and not quality["known_errors"] and not quality["duplicates"]
                  and result.get("stop_reason") == "sources_exhausted" and not changed)
    return {"theme": theme, "route": route, "model": MODEL if route == "byok" else os.environ.get("TIMELINE_MODEL", "gemma4:12b"),
            "verify_model": MODEL if route == "byok" else os.environ.get("TIMELINE_VERIFY_MODEL", "qwen3.8:27b"),
            "conditions": {"source": "wikipedia", "source_filter": os.environ.get("TIMELINE_SOURCE_FILTER", ""),
                           "footnote_filter": os.environ.get("TIMELINE_FOOTNOTE_FILTER", ""),
                           "options": options, "sha256": hashes},
            "code_changed_during_run": changed,
            "state": "complete" if result else "failed", "error": "code_changed" if changed else None if result else error,
            "elapsed_seconds": round(time.monotonic() - start, 1), "usage": usage, "material": material, "quality": quality,
            "passed": passed, "result": result_view(result) if result else None,
            "limitations": "Live Wikipedia inputs can change; automatic recall is not an independent source audit. Operator fee is zero API fee, not zero infrastructure cost."}


def compare(left, right):
    if left.get("code_changed_during_run") or right.get("code_changed_during_run"):
        raise ValueError("Code changed during measurement; cannot compare")
    if {left["route"], right["route"]} != {"byok", "operator"}:
        raise ValueError("One BYOK and one operator measurement required")
    if left["theme"] != right["theme"] or left["conditions"] != right["conditions"]:
        raise ValueError("Theme, code, gold and retrieval conditions must match")
    return {"theme": left["theme"], "passed": left["passed"] and right["passed"],
            "cases": [left, right], "source_audit_required": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", choices=("byok", "operator"))
    parser.add_argument("--theme")
    parser.add_argument("--max-usd")
    parser.add_argument("--time-limit", type=int, default=3600)
    parser.add_argument("--model-calls", type=int, default=60,
                        help="Explicit BYOK call cap, 1 through 100; default 60")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", nargs=2, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output already exists; paid runs are never resumed or overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reserve the output before any hidden key input or paid operation.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if args.compare:
            report = compare(*(json.loads(path.read_text()) for path in args.compare))
        else:
            if not args.route or not args.theme or args.max_usd is None:
                parser.error("Explicit route, fixed theme and max-usd required")
            golds = [json.loads((ROOT / name).read_text()) for name in ("quality_gold.json", "quality_holdout.json")]
            if not any(args.theme in g["themes"] for g in golds):
                parser.error("Use a theme in the existing fixed evaluation sets")
            try:
                amount = Decimal(args.max_usd) * 1_000_000
                if not amount.is_finite() or amount != amount.to_integral_value():
                    raise ValueError
                options = configuration(args.time_limit, int(amount), args.model_calls)
            except (ValueError, InvalidOperation, OverflowError):
                parser.error("Cost must be USD 0.000001 through 5; time-limit 1 through 3600; model-calls 1 through 100")
            key = None
            if args.route == "byok":
                if not os.isatty(0):
                    parser.error("A terminal is required for hidden key input; no key in argv/env/files")
                print(f"Google Gemini {MODEL}; maximum USD {args.max_usd}, standard text rate estimate.\n"
                      f"Maximum {args.model_calls} model calls; no automatic retries or resume.\n"
                      f"Calls start at least {MIN_CALL_INTERVAL} seconds apart; this is not a guarantee of free-tier quota.\n"
                      "Prompts/results go to Google. Free-tier data may be used for improvement and human review.\n"
                      "For adult developer evaluation only; public release is not enabled.\n"
                      "Cancellation cannot reverse an in-flight provider charge.")
                key = getpass.getpass("Your Google AI Studio API key (not saved): ")
                validate_key(key)
            report = measure(args.theme, args.route, key, options)
            key = None
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({"state": report.get("state"), "error": report.get("error"),
                          "passed": report["passed"], "usage": report.get("usage")}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
