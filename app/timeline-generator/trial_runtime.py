"""Single trial worker and retention maintenance; explicitly wired, never auto-started."""
import re
import os
import threading
import time

from public_pipeline import bounded_generation
from public_security import PublicError, receipt_view, result_view
from trial import ReceiptConflict, ReceiptGone, TrialLimit


def request_input(value):
    if not isinstance(value, dict) or set(value) != {"receipt_id", "query"}:
        raise PublicError(400, "invalid_request")
    identifier, query = value["receipt_id"], value["query"]
    if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", identifier)
            or not isinstance(query, str) or re.search(r"[\ud800-\udfff]", query)):
        raise PublicError(400, "invalid_request")
    from timeline import parse_query, TimelineError
    try:
        # Keep the existing keyword contract; NFKC and whitespace variants replay identically.
        return identifier, parse_query(query).topic
    except TimelineError:
        raise PublicError(400, "invalid_query") from None


class Cancellation:
    def __init__(self, runtime, receipt):
        self.runtime, self.receipt = runtime, receipt

    def is_set(self):
        if self.runtime.stopping.is_set():
            return True
        item = self.runtime.ledger.get(self.receipt["owner"], self.receipt["receipt_id"])
        return item is None or item["state"] != "running"


class TrialRuntime:
    def __init__(self, ledger, backup_directory, *, generate=bounded_generation,
                 maintenance_interval=60, backup_interval=86400):
        if not 0 < maintenance_interval <= 3600 or not 0 < backup_interval <= 86400:
            raise ValueError("Invalid maintenance interval")
        if generate is bounded_generation and os.environ.get("TIMELINE_SOURCE") != "wikipedia":
            raise ValueError("Public trial requires TIMELINE_SOURCE=wikipedia")
        self.ledger, self.backup_directory, self.generate = ledger, backup_directory, generate
        self.maintenance_interval, self.backup_interval = maintenance_interval, backup_interval
        self.stopping, self.wake = threading.Event(), threading.Event()
        self.lock = threading.RLock()
        self.failed, self.started = False, False
        self.last_backup = None
        self.worker = threading.Thread(target=self.run, name="public-trial-worker", daemon=True)
        self.maintenance = threading.Thread(target=self.maintain, name="public-trial-maintenance", daemon=True)

    def start(self):
        with self.lock:
            if self.started:
                raise ValueError("Trial runtime already started")
            self.started = True
            # Refuse acceptance if initial purge or backup fails.
            self.maintain_once()
            self.worker.start()
            self.maintenance.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        for thread in (self.worker, self.maintenance):
            if thread.ident is not None:
                thread.join(timeout=6)
        if self.worker.is_alive() or self.maintenance.is_alive():
            raise RuntimeError("Trial runtime did not stop; keep ledger open")

    def fail(self):
        with self.lock:
            self.failed = True
            self.stopping.set()
            self.wake.set()

    def accept(self, owner, value):
        identifier, query = request_input(value)
        with self.lock:
            if (self.failed or self.stopping.is_set() or not self.worker.is_alive()
                    or not self.maintenance.is_alive()):
                raise PublicError(503, "trial_unavailable")
            try:
                row, created = self.ledger.accept(owner, identifier, "new", {"query": query})
            except ReceiptConflict:
                raise PublicError(409, "receipt_conflict") from None
            except ReceiptGone:
                raise PublicError(410, "receipt_gone") from None
            except TrialLimit:
                raise
            except Exception:
                self.fail()
                raise PublicError(503, "trial_unavailable") from None
            self.wake.set()
        return receipt_view(row), created

    def maintain_once(self):
        self.ledger.purge()
        moment = time.monotonic()
        if self.last_backup is None or moment - self.last_backup >= self.backup_interval:
            self.ledger.backup(self.backup_directory)
            self.last_backup = moment

    def maintain(self):
        try:
            while not self.stopping.wait(self.maintenance_interval):
                self.maintain_once()
        except Exception:
            self.fail()

    def run(self):
        try:
            while not self.stopping.is_set():
                receipt = self.ledger.claim()
                if receipt is None:
                    self.wake.wait(0.2)
                    self.wake.clear()
                    continue
                cancellation = Cancellation(self, receipt)
                result = None

                def emit(record):
                    nonlocal result
                    if isinstance(record, dict) and record.get("kind") == "result":
                        # Store only the same whitelist that can be returned to the owner.
                        result = {"kind": "result", **result_view(record)}

                try:
                    query = request_input({"receipt_id": receipt["receipt_id"],
                                           "query": receipt["payload"]["query"]})[1]
                    if not cancellation.is_set():
                        self.generate(query, emit, cancellation)
                except Exception:
                    result = None
                if not self.stopping.is_set():
                    # finish is conditional on running: late results never revive a cancellation.
                    self.ledger.finish(receipt["owner"], receipt["receipt_id"], result)
        except Exception:
            self.fail()
