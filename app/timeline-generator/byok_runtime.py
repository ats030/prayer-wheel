"""Ephemeral authenticated BYOK receipts. Trial accounting is never accessed."""
from dataclasses import dataclass, fields
import hashlib
import json
import os
import threading
import time

from byok import ByokError, MODEL, PROVIDER, validate_key
from byok_pipeline import bounded_byok
from public_security import PublicError, result_view
from trial_runtime import request_input


@dataclass(frozen=True)
class ByokLimits:
    concurrent: int
    starts: int
    owners: int
    receipts: int
    ttl: int
    time_limit: int
    fetch_calls: int
    fetch_bytes: int
    model_calls: int
    input_bytes: int
    output_tokens: int
    max_cost_microusd: int

    def __post_init__(self):
        upper = (8, 100, 10000, 1000, 3600, 3600, 200, 100_000_000,
                 100, 160_000, 8192, 5_000_000)
        if any(type(getattr(self, f.name)) is not int or not 1 <= getattr(self, f.name) <= cap
               for f, cap in zip(fields(self), upper)):
            raise ValueError("Explicit bounded BYOK limits required")
        if self.ttl < self.time_limit:
            raise ValueError("Receipt lifetime must cover processing time")

    @classmethod
    def from_env(cls):
        try:
            return cls(**{f.name: int(os.environ["TIMELINE_BYOK_" + f.name.upper()]) for f in fields(cls)})
        except (KeyError, ValueError):
            raise ValueError("All TIMELINE_BYOK limits must be explicitly configured") from None


class GenerationSlots:
    """Shared with the trial runtime when both use this server's resources."""
    def __init__(self, concurrent):
        if type(concurrent) is not int or not 1 <= concurrent <= 8:
            raise ValueError("Explicit generation concurrency required")
        self.semaphore = threading.BoundedSemaphore(concurrent)

    def acquire(self):
        return self.semaphore.acquire(blocking=False)

    def release(self):
        self.semaphore.release()


class ByokRuntime:
    def __init__(self, limits, *, slots, generate=bounded_byok, clock=time.monotonic):
        if not isinstance(limits, ByokLimits) or not isinstance(slots, GenerationSlots):
            raise ValueError("BYOK limits and shared generation slots required")
        if generate is bounded_byok and os.environ.get("TIMELINE_SOURCE") != "wikipedia":
            raise ValueError("BYOK requires TIMELINE_SOURCE=wikipedia")
        self.limits, self.slots, self.generate, self.clock = limits, slots, generate, clock
        self.lock = threading.RLock()
        self.rows, self.running, self.rates = {}, {}, {}
        self.bucket = None
        self.stopped = False

    def prune(self):
        moment = self.clock()
        for identifier, row in list(self.rows.items()):
            if row["expires"] <= moment:
                if identifier in self.running:
                    self.running[identifier][0].set()
                del self.rows[identifier]
        bucket = int(moment // 60)
        if bucket != self.bucket:
            self.bucket, self.rates = bucket, {}

    def view(self, row):
        output = {k: row[k] for k in ("receipt_id", "state", "error", "result", "usage", "charge_may_continue") if k in row}
        output.update({"route": "byok", "provider": PROVIDER, "model": MODEL,
                       "expires_in": max(0, int(row["expires"] - self.clock()))})
        return output

    def accept(self, owner, value):
        if not isinstance(value, dict) or set(value) != {"receipt_id", "query", "api_key", "max_cost_microusd"}:
            raise PublicError(400, "invalid_request")
        identifier, query = request_input({k: value[k] for k in ("receipt_id", "query")})
        try:
            validate_key(value["api_key"])
        except ByokError:
            raise PublicError(400, "invalid_api_key") from None
        cap = value["max_cost_microusd"]
        if type(cap) is not int or not 1 <= cap <= self.limits.max_cost_microusd:
            raise PublicError(400, "invalid_cost_limit")
        # Replay identity excludes the key: a retransmitted acceptance must not
        # spend again, even if the caller has since changed/rotated credentials.
        fingerprint = hashlib.sha256(json.dumps([query, cap], ensure_ascii=False).encode()).digest()
        with self.lock:
            self.prune()
            if self.stopped:
                raise PublicError(503, "byok_unavailable")
            previous = self.rows.get(identifier)
            if previous is None and identifier in self.running:
                raise PublicError(410, "receipt_gone")
            if previous is not None:
                if previous["owner"] != owner:
                    raise PublicError(409, "receipt_conflict")
                if previous["fingerprint"] != fingerprint:
                    raise PublicError(409, "receipt_conflict")
                return self.view(previous), False
            if len(self.rates) >= self.limits.owners and owner not in self.rates:
                raise PublicError(429, "request_rate")
            if self.rates.get(owner, 0) >= self.limits.starts:
                raise PublicError(429, "request_rate")
            if (len(self.rows) >= self.limits.receipts or len(self.running) >= self.limits.concurrent
                    or not self.slots.acquire()):
                raise PublicError(503, "server_busy")
            stopping = threading.Event()
            row = {"receipt_id": identifier, "owner": owner, "fingerprint": fingerprint,
                   "expires": self.clock() + self.limits.ttl, "state": "running"}
            options = {f.name: getattr(self.limits, f.name) for f in fields(self.limits)}
            options["max_cost_microusd"] = cap
            worker = threading.Thread(target=self.run,
                args=(identifier, query, value["api_key"], options, stopping), daemon=True,
                name="byok-generation")
            self.rows[identifier] = row
            self.running[identifier] = (stopping, worker)
            self.rates[owner] = self.rates.get(owner, 0) + 1
            try:
                worker.start()
            except Exception:
                del self.rows[identifier], self.running[identifier]
                self.slots.release()
                raise PublicError(503, "byok_unavailable") from None
            return self.view(row), True

    def run(self, identifier, query, key, options, stopping):
        result, usage, error = None, None, "processing_error"
        def emit(record):
            nonlocal result, usage, error
            if not isinstance(record, dict):
                return
            if record.get("kind") == "result":
                result = result_view(record)
            elif record.get("kind") == "usage":
                candidate = record.get("usage")
                # Whitelist statistics, never a provider response, key or prompt.
                names = ("calls", "input_tokens", "output_tokens", "cost_microusd", "max_cost_microusd")
                if (isinstance(candidate, dict) and all(type(candidate.get(k)) is int and candidate[k] >= 0 for k in names)
                        and type(candidate.get("cost_is_upper_bound")) is bool):
                    usage = {k: candidate[k] for k in (*names, "cost_is_upper_bound")}
                    with self.lock:
                        row = self.rows.get(identifier)
                        if row is not None:
                            row["usage"] = usage
            elif record.get("kind") == "ended":
                known = {"time_limit", "cost_budget", "input_budget", "fetch_budget", "fetch_route",
                         "invalid_api_key", "provider_denied", "provider_rate", "provider_unavailable",
                         "provider_response", "provider_usage", "provider_request", "processing_error"}
                if record.get("error") is not None:
                    result = None
                    error = record.get("error") if record.get("error") in known else "processing_error"
        try:
            self.generate(query, key, options, emit, stopping)
        except Exception:
            result = None
        finally:
            key = None
            with self.lock:
                row = self.rows.get(identifier)
                if row is not None and stopping.is_set():
                    row["state"] = "cancelled"
                    # A killed/in-flight request may still be charged by the
                    # provider. Never display cancellation as a fee refund.
                    row["charge_may_continue"] = True
                    if usage is not None:
                        row["usage"] = usage
                if row is not None and not stopping.is_set() and row["state"] == "running":
                    row["state"] = "complete" if result is not None else "failed"
                    if result is not None:
                        row["result"] = result
                    else:
                        row["error"] = error
                    if usage is not None:
                        row["usage"] = usage
                self.running.pop(identifier, None)
                self.slots.release()

    def receipt(self, owner, identifier, *, cancel=False, received=False):
        with self.lock:
            self.prune()
            row = self.rows.get(identifier)
            if row is None or row["owner"] != owner:
                raise PublicError(404, "receipt_not_found")
            if cancel:
                if row["state"] not in {"running", "cancelled"}:
                    raise PublicError(409, "receipt_state")
                if identifier in self.running:
                    self.running[identifier][0].set()
                row["state"] = "cancelled"
            if received:
                if row["state"] != "complete":
                    raise PublicError(409, "receipt_state")
                row["expires"] = min(row["expires"], self.clock() + 600)
            return self.view(row)

    def stop(self):
        with self.lock:
            self.stopped = True
            workers = list(self.running.values())
            for stopping, _ in workers:
                stopping.set()
        for _, worker in workers:
            worker.join(timeout=6)
        if any(worker.is_alive() for _, worker in workers):
            raise RuntimeError("BYOK workers did not stop")
        with self.lock:
            self.rows.clear()
