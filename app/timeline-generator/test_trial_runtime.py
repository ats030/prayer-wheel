"""Offline trial HTTP/worker/maintenance integration. No Google/model/article calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from google_login import GoogleLogin, ISSUER
from public_pipeline import bounded_generation
from public_security import PublicBoundary, COOKIE, PublicError
from public_server import make_server
from test_google_login import CLIENT, ORIGIN
from test_public_security import result
import test_public_server
from test_trial import Clock, rid
from trial import TrialLedger
from trial_runtime import TrialRuntime


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition did not become true")


def slow_child(query, connection):
    connection.send({"kind": "progress"})
    time.sleep(20)


def checkpoint_child(query, connection):
    connection.send({**result(), "kind": "checkpoint"})
    time.sleep(20)


class TrialIntegrationTests(unittest.TestCase):
    request = test_public_server.PublicServerTests.request

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock(datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
        self.ledger = TrialLedger(Path(self.temp.name) / "trial.sqlite3", self.clock)
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = []
        self.runtime = TrialRuntime(self.ledger, Path(self.temp.name) / "backups",
                                    generate=self.generate, maintenance_interval=0.05)
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.login = GoogleLogin(boundary, CLIENT, "offline-secret", exchange=lambda _: None)
        token, session = boundary.issue_verified(ISSUER, "owner-one")
        self.owner = session.owner
        self.headers = {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN,
                        "Content-Type": "application/json", "X-CSRF-Token": session.csrf}
        self.server = make_server(self.login, port=0, runtime=self.runtime)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.runtime.start()

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.runtime.stop()
        self.ledger.close()
        self.temp.cleanup()

    def generate(self, query, emit, cancellation):
        self.calls.append(query)
        self.entered.set()
        while not self.release.wait(0.01):
            if cancellation.is_set():
                return
        emit(result())

    def submit(self, number, query="昭和", extra=None, headers=None):
        body = {"receipt_id": rid(number), "query": query, **(extra or {})}
        return self.request("POST", "/api/trial/receipts", json.dumps(body),
                            self.headers if headers is None else headers)

    def test_accept_run_retrieve_receive_and_purge(self):
        status, _, raw = self.submit(1)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(raw)["state"], "queued")
        self.assertTrue(self.entered.wait(2))
        self.release.set()
        wait_for(lambda: self.ledger.get(self.owner, rid(1))["state"] == "complete")
        path = "/api/receipts/" + rid(1)
        status, _, raw = self.request("GET", path, headers=self.headers)
        self.assertEqual(status, 200)
        for secret in (b'"quote"', b'"trace"', b'"api_key"', b'"owner"', b'"payload"'):
            self.assertNotIn(secret, raw)
        stored = self.ledger.get(self.owner, rid(1))["result"]
        self.assertNotIn("api_key", stored)
        self.assertNotIn("quote", stored["events"][0])
        self.assertEqual(self.request("POST", path + "/received", "{}", self.headers)[0], 200)
        self.clock.advance(minutes=10)
        wait_for(lambda: self.result_count() == 0)
        self.assertEqual(self.request("GET", path, headers=self.headers)[0], 410)
        self.assertEqual(self.ledger.usage()["used"], 1)

    def result_count(self):
        with self.ledger.transaction(write=False) as db:
            return db.execute("SELECT count(*) FROM results").fetchone()[0]

    def test_auth_csrf_body_and_fixed_route(self):
        self.assertEqual(self.submit(1, headers={"Origin": ORIGIN, "Content-Type": "application/json"})[0], 401)
        self.assertEqual(self.submit(1, headers={k: v for k, v in self.headers.items() if k != "X-CSRF-Token"})[0], 403)
        for extra in ({"owner": "other"}, {"mode": "byok"}, {"source_mode": "wikipedia"},
                      {"api_key": "secret"}, {"url": "http://127.0.0.1"}, {"operation": "retry"}):
            self.assertEqual(self.submit(1, extra=extra)[0], 400)
        for query in ("", "x" * 181, "昭和\n秘密", "昭和 1900年", "\ud800"):
            self.assertEqual(self.submit(1, query=query)[0], 400)
        raw = '{"receipt_id":"' + rid(1) + '","query":"one","query":"two"}'
        self.assertEqual(self.request("POST", "/api/trial/receipts", raw, self.headers)[0], 400)
        self.assertEqual(self.ledger.usage()["used"], 0)
        self.assertEqual(self.request("GET", "/api/trial/receipts", headers=self.headers)[0], 404)

    def test_replay_normalization_conflict_and_deleted(self):
        self.assertEqual(self.submit(1, "  昭和  ")[0], 201)
        self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.submit(1, "昭和")[0], 200)
        self.assertEqual(self.submit(1, "別テーマ")[0], 409)
        path = "/api/receipts/" + rid(1)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", self.headers)[0], 200)
        self.assertEqual(json.loads(self.submit(1)[2])["state"], "cancelled")
        self.assertEqual(self.calls, ["昭和"])
        self.ledger.delete(self.owner, rid(1))
        self.assertEqual(self.submit(1)[0], 410)

    def test_twenty_parallel_http_accepts_respect_pending_limit(self):
        with ThreadPoolExecutor(20) as pool:
            outcomes = list(pool.map(self.submit, range(20)))
        self.assertEqual(sum(status == 201 for status, _, _ in outcomes), 3)
        for status, headers, raw in outcomes:
            if status == 429:
                self.assertEqual(json.loads(raw), {"error": "trial_pending"})
                self.assertIn(("Retry-After", "60"), headers)
        self.assertEqual(self.ledger.usage()["pending"], 3)

    def test_twenty_parallel_http_accepts_respect_daily_limit(self):
        # Raise only the pending bound in the fixture to exercise the independent daily bound.
        with patch("trial.PENDING_LIMIT", 100):
            with ThreadPoolExecutor(20) as pool:
                outcomes = list(pool.map(self.submit, range(20)))
        self.assertEqual(sum(status == 201 for status, _, _ in outcomes), 10)
        for status, headers, raw in outcomes:
            if status == 429:
                self.assertEqual(json.loads(raw), {"error": "trial_daily"})
                self.assertTrue(int(dict(headers)["Retry-After"]) > 0)
        self.assertEqual(self.ledger.usage()["used"], 10)

    def test_cancel_queued_refunds_running_does_not_and_late_result_is_discarded(self):
        self.submit(1)
        self.assertTrue(self.entered.wait(2))
        self.submit(2)
        for number in (2, 1):
            self.assertEqual(self.request("POST", "/api/receipts/" + rid(number) + "/cancel", "{}", self.headers)[0], 200)
        self.release.set()
        wait_for(lambda: self.ledger.usage()["pending"] == 0)
        self.assertEqual(self.ledger.usage()["used"], 1)
        for number in (1, 2):
            self.assertEqual(self.ledger.get(self.owner, rid(number))["state"], "cancelled")
        self.assertEqual(self.result_count(), 0)
        self.assertEqual(self.calls, ["昭和"])

    def test_unhealthy_runtime_refuses_new_acceptance(self):
        with patch.object(self.ledger, "purge", side_effect=OSError("private storage details")):
            wait_for(lambda: self.runtime.failed)
        status, _, raw = self.submit(1)
        self.assertEqual((status, json.loads(raw)), (503, {"error": "trial_unavailable"}))
        self.assertEqual(self.ledger.usage()["used"], 0)
        self.assertNotIn(b"private", raw)

    def test_periodic_backup_removes_old_snapshot(self):
        folder = Path(self.temp.name) / "backups"
        first = list(folder.glob("trial-*.sqlite3"))[0]
        self.clock.advance(days=8)
        self.runtime.backup_interval = 0.01
        wait_for(lambda: not first.exists())
        self.assertTrue(list(folder.glob("trial-*.sqlite3")))

    def test_storage_bound_is_independent_of_refunded_ai_quota(self):
        with patch("trial.MAX_RECEIPTS", 1):
            self.submit(1)
            self.assertTrue(self.entered.wait(2))
            self.request("POST", "/api/receipts/" + rid(1) + "/cancel", "{}", self.headers)
            status, headers, raw = self.submit(2)
            self.assertEqual((status, json.loads(raw)), (429, {"error": "trial_storage"}))
            self.assertIn(("Retry-After", "3600"), headers)


class ProcessAndLifecycleTests(unittest.TestCase):
    def test_process_timeout_and_checkpoint(self):
        before = {p.pid for p in multiprocessing.active_children()}
        for child, count in ((slow_child, 0), (checkpoint_child, 1)):
            records = []
            bounded_generation("昭和", records.append, threading.Event(), time_limit=0.8, child=child)
            self.assertEqual(len(records), count)
            if records:
                self.assertEqual(records[0]["source_mode"], "wikipedia")
                self.assertEqual(records[0]["stop_reason"], "time_limit")
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)

    def test_running_cancel_stops_child_and_next_generation_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = TrialLedger(Path(folder) / "trial.sqlite3")
            entered = threading.Event()

            def generate(query, emit, token):
                if query == "slow":
                    entered.set()
                    bounded_generation(query, emit, token, child=slow_child)
                else:
                    emit(result())

            runtime = TrialRuntime(ledger, Path(folder) / "backups", generate=generate)
            runtime.start()
            try:
                runtime.accept("owner", {"receipt_id": rid(1), "query": "slow"})
                self.assertTrue(entered.wait(2))
                wait_for(lambda: bool(multiprocessing.active_children()))
                ledger.cancel("owner", rid(1))
                runtime.accept("owner", {"receipt_id": rid(2), "query": "next"})
                wait_for(lambda: ledger.get("owner", rid(2))["state"] == "complete")
                self.assertFalse(multiprocessing.active_children())
                self.assertEqual(ledger.get("owner", rid(1))["state"], "cancelled")
            finally:
                runtime.stop()
                ledger.close()

    def test_generation_error_and_invalid_result_fail_without_private_details(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = TrialLedger(Path(folder) / "trial.sqlite3")
            def generate(query, emit, token):
                if query == "error":
                    raise RuntimeError("private API key")
                if query == "invalid":
                    emit({**result(), "source_mode": "searxng"})
                else:
                    emit(result())
            runtime = TrialRuntime(ledger, Path(folder) / "backups", generate=generate)
            runtime.start()
            try:
                for number, query in enumerate(("error", "invalid", "valid")):
                    runtime.accept("owner", {"receipt_id": rid(number), "query": query})
                    wait_for(lambda: ledger.get("owner", rid(number))["state"] != "queued"
                             and ledger.get("owner", rid(number))["state"] != "running")
                    self.assertEqual(ledger.get("owner", rid(number))["state"], "complete" if query == "valid" else "failed")
                self.assertTrue(runtime.worker.is_alive())
            finally:
                runtime.stop()
                ledger.close()

    def test_start_refuses_backup_failure_and_default_non_wikipedia_route(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = TrialLedger(Path(folder) / "trial.sqlite3")
            try:
                with patch.dict(os.environ, {"TIMELINE_SOURCE": "searxng"}):
                    with self.assertRaises(ValueError):
                        TrialRuntime(ledger, Path(folder) / "backups")
                runtime = TrialRuntime(ledger, Path(folder) / "backups", generate=lambda *args: None)
                with patch.object(ledger, "backup", side_effect=OSError("disk")):
                    with self.assertRaises(OSError):
                        runtime.start()
                with self.assertRaises(PublicError) as caught:
                    runtime.accept("owner", {"receipt_id": rid(1), "query": "昭和"})
                self.assertEqual(caught.exception.status, 503)
                runtime.stop()
            finally:
                ledger.close()

    def test_stop_preserves_started_receipt_for_restart_without_refund(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "trial.sqlite3"
            ledger = TrialLedger(path)
            entered = threading.Event()
            def generate(query, emit, token):
                entered.set()
                while not token.is_set():
                    time.sleep(0.01)
            runtime = TrialRuntime(ledger, Path(folder) / "backups", generate=generate)
            runtime.start()
            try:
                runtime.accept("owner", {"receipt_id": rid(1), "query": "昭和"})
                self.assertTrue(entered.wait(2))
                runtime.stop()
                self.assertEqual(ledger.get("owner", rid(1))["state"], "running")
            finally:
                runtime.stop()
                ledger.close()
            recovered = TrialLedger(path)
            try:
                self.assertEqual(recovered.get("owner", rid(1))["state"], "queued")
                self.assertFalse(recovered.cancel("owner", rid(1))["refunded"])
                self.assertEqual(recovered.usage()["used"], 1)
            finally:
                recovered.close()

    def test_worker_storage_failure_closes_intake(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = TrialLedger(Path(folder) / "trial.sqlite3")
            runtime = TrialRuntime(ledger, Path(folder) / "backups", generate=lambda *args: None)
            try:
                with patch.object(ledger, "claim", side_effect=OSError("private database")):
                    runtime.start()
                    wait_for(lambda: runtime.failed)
                with self.assertRaises(PublicError) as caught:
                    runtime.accept("owner", {"receipt_id": rid(1), "query": "昭和"})
                self.assertEqual((caught.exception.status, caught.exception.code), (503, "trial_unavailable"))
            finally:
                runtime.stop()
                ledger.close()


if __name__ == "__main__":
    unittest.main()
