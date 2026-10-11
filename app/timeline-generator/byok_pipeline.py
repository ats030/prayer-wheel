"""Spawn-only BYOK job: key never enters a durable queue or trial ledger."""
import http.client
import json
import multiprocessing
import os
import threading
import time
from urllib.parse import urlsplit

from byok import ByokError, ModelSession


class FetchBudget:
    def __init__(self, calls, byte_limit):
        if (type(calls) is not int or not 1 <= calls <= 200
                or type(byte_limit) is not int or not 1 <= byte_limit <= 100_000_000):
            raise ValueError("Explicit retrieval limits required")
        self.max_calls, self.max_bytes = calls, byte_limit
        self.calls = self.bytes = 0
        self.lock = threading.Lock()

    def check(self, url):
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname not in {"ja.wikipedia.org", "en.wikipedia.org"}
                or p.port not in (None, 443) or p.username or p.password
                or not (p.path in {"/w/api.php", "/robots.txt"} or p.path.startswith("/wiki/"))):
            raise ByokError("fetch_route")
        if self.calls >= self.max_calls or self.bytes >= self.max_bytes:
            raise ByokError("fetch_budget")
        self.calls += 1
        return min(3_000_000, self.max_bytes - self.bytes)

    def json(self, url, payload=None, timeout=20):
        # Search is read-only Wikipedia; never send API credentials here.
        if payload is not None:
            raise ByokError("fetch_route")
        with self.lock:
            limit = self.check(url)
            p = urlsplit(url)
            connection = http.client.HTTPSConnection(p.hostname, timeout=min(20, timeout))
            try:
                from timeline import USER_AGENT
                connection.request("GET", p.path + ("?" + p.query if p.query else ""),
                                   headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
                response = connection.getresponse()
                body = response.read(limit + 1)
                self.bytes += len(body)
                if len(body) > limit:
                    raise ByokError("fetch_budget")
                if response.status != 200:
                    raise OSError("Wikipedia unavailable")
                return json.loads(body)
            finally:
                connection.close()

    def article(self, request, reader, url, limit=2_000_000):
        with self.lock:
            allowed = min(limit, self.check(url))
            # Existing DNS-pinned retrieval and robots checks remain in force.
            self.bytes += allowed
            try:
                status, headers, body, final = request(reader, url, allowed)
            except Exception:
                if self.bytes >= self.max_bytes:
                    raise ByokError("fetch_budget") from None
                raise
            if len(body) > allowed:
                raise ByokError("fetch_budget")
            self.bytes += len(body) - allowed
            return status, headers, body, final


def generate_child(query, key, options, connection):
    model = None
    try:
        os.environ["TIMELINE_SOURCE"] = "wikipedia"
        import timeline
        if timeline.SOURCE != "wikipedia":
            raise ByokError("fetch_route")
        budget = FetchBudget(options["fetch_calls"], options["fetch_bytes"])
        # Only this disposable process is adapted; no private/operator worker
        # shares these bindings, and every retrieval thread shares the budget.
        timeline.json_request = budget.json
        request = timeline.WebReader.request
        timeline.WebReader.request = lambda reader, url, limit=2_000_000: budget.article(request, reader, url, limit)
        model = ModelSession(key, threading.Event(), max_cost_microusd=options["max_cost_microusd"],
                             max_calls=options["model_calls"], input_bytes=options["input_bytes"],
                             output_tokens=options["output_tokens"],
                             on_usage=lambda usage: connection.send({"kind": "usage", "usage": usage}))
        key = None
        def emit(record):
            # Public result whitelist runs in the parent; quotes/trace never
            # enter the HTTP receipt store or backup.
            connection.send(record)
            connection.send({"kind": "usage", "usage": model.summary(),
                             "fetch": {"calls": budget.calls, "bytes": budget.bytes}})
        result = timeline.build_timeline(timeline.parse_query(query), emit, model=model)
        emit(result)
    except Exception as exc:
        connection.send({"kind": "error", "error": exc.code if isinstance(exc, ByokError) else "processing_error"})
    finally:
        key = None
        if model is not None:
            connection.send({"kind": "usage", "usage": model.summary()})
            model.close()
        connection.close()


def bounded_byok(query, key, options, emit, stopping, *, child=generate_child):
    """No restoration, retry, fallback or operator-model entry point."""
    if stopping.is_set():
        return
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=child, args=(query, key, options, sender), daemon=True)
    deadline = time.monotonic() + options["time_limit"]
    error = "processing_error"
    result = None
    try:
        process.start()
        key = None
        sender.close()
        # No partial result is silently promoted after a provider/budget error.
        # Usage is delivered separately even for failed/cancelled jobs.
        while time.monotonic() < deadline:
            if stopping.is_set():
                return
            try:
                if receiver.poll(min(0.2, max(0, deadline - time.monotonic()))):
                    record = receiver.recv()
                    if not isinstance(record, dict):
                        break
                    if record.get("kind") == "result":
                        result = record
                    elif record.get("kind") == "usage":
                        emit(record)
                    elif record.get("kind") == "error":
                        error = record.get("error", "processing_error")
                        result = None
                    # Drain the final usage record before accepting completion.
                elif not process.is_alive():
                    break
            except (EOFError, OSError):
                break
        else:
            error = "time_limit"
            result = None
        if not stopping.is_set():
            process.join(timeout=0.2)
            if process.is_alive() or process.exitcode != 0:
                result = None
            if result is not None:
                emit(result)
            emit({"kind": "ended", "error": None if result is not None else error})
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            process.close()
