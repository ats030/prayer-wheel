"""Offline authenticated HTTP and trial-ledger separation for BYOK."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from byok_runtime import ByokLimits, ByokRuntime, GenerationSlots
from google_login import GoogleLogin, ISSUER
from public_security import COOKIE, PublicBoundary, PublicError
from public_server import make_server
from test_byok import KEY
from test_google_login import CLIENT, ORIGIN
from test_public_security import result
import test_public_server
from test_trial import rid
from test_trial_runtime import wait_for
from trial import TrialLedger
from trial_runtime import TrialRuntime


def limits(**overrides):
    return ByokLimits(**{"concurrent": 1, "starts": 20, "owners": 100, "receipts": 100,
        "ttl": 600, "time_limit": 300, "fetch_calls": 50, "fetch_bytes": 20_000_000,
        "model_calls": 30, "input_bytes": 100_000, "output_tokens": 6000,
        "max_cost_microusd": 500_000, **overrides})


class ByokHttpTests(unittest.TestCase):
    request = test_public_server.PublicServerTests.request

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = TrialLedger(Path(self.temp.name) / "trial.sqlite3",
                                  clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls = []
        self.slots = GenerationSlots(1)
        self.byok = ByokRuntime(limits(), slots=self.slots, generate=self.generate)
        self.trial = TrialRuntime(self.ledger, Path(self.temp.name) / "backups", slots=self.slots,
                                  generate=lambda *_: self.fail("Unexpected operator AI"))
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.login = GoogleLogin(boundary, CLIENT, "offline-secret", exchange=lambda _: None)
        token, session = boundary.issue_verified(ISSUER, "owner-one")
        self.owner = session.owner
        self.headers = {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN,
                        "Content-Type": "application/json", "X-CSRF-Token": session.csrf}
        self.server = make_server(self.login, port=0, runtime=self.trial, byok=self.byok)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.trial.start()

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.byok.stop()
        self.trial.stop()
        self.ledger.close()
        self.temp.cleanup()

    def generate(self, query, key, options, emit, stopping):
        self.calls.append((query, options["max_cost_microusd"]))
        self.assertEqual(key, KEY)
        self.entered.set()
        while not self.release.wait(0.01):
            if stopping.is_set():
                return
        emit({"kind": "usage", "usage": {"calls": 2, "input_tokens": 1000, "output_tokens": 100,
            "cost_microusd": 1500, "max_cost_microusd": 100_000, "cost_is_upper_bound": False, "api_key": KEY,
            "failure_detail": {"stage": "generate", "kind": "http", "http_status": 503, "message": KEY}}})
        emit(result())

    def submit(self, n, **extra):
        value = {"receipt_id": rid(n), "query": "昭和", "api_key": KEY, "max_cost_microusd": 100_000, **extra}
        return self.request("POST", "/api/byok/receipts", json.dumps(value), self.headers)

    def snapshot(self):
        with self.ledger.transaction(write=False) as db:
            return list(db.iterdump())

    def test_full_trial_accepts_byok_new_replay_cancel_retry_without_ledger_changes(self):
        for n in range(10):
            self.ledger.accept(self.owner, rid(100 + n), "new", {"query": "昭和"})
            self.ledger.claim()
            self.ledger.finish(self.owner, rid(100 + n), None)
        before = self.snapshot()
        self.assertEqual(self.ledger.usage()["used"], 10)
        self.assertEqual(self.submit(1)[0], 201)
        self.assertTrue(self.entered.wait(2))
        self.assertEqual(self.submit(1)[0], 200)
        self.assertEqual(len(self.calls), 1)
        path = "/api/byok/receipts/" + rid(1)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", self.headers)[0], 200)
        wait_for(lambda: not self.byok.running)
        self.assertEqual(self.submit(1)[0], 200)
        self.assertEqual(len(self.calls), 1)
        # A retry is an explicit fresh receipt with a fresh key submission/cap.
        self.release.set()
        self.assertEqual(self.submit(2)[0], 201)
        wait_for(lambda: self.byok.rows[rid(2)]["state"] == "complete")
        status, _, raw = self.request("GET", "/api/byok/receipts/" + rid(2), headers=self.headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["usage"]["cost_microusd"], 1500)
        for secret in (KEY.encode(), b'"api_key"', b'"owner"', b'"fingerprint"', b'"quote"', b'"trace"', b'"failure_detail"'):
            self.assertNotIn(secret, raw)
        self.assertEqual(self.snapshot(), before)
        # Explicit trial switch uses its own new intake and reserves quota before AI.
        body = json.dumps({"receipt_id": rid(3), "query": "昭和"})
        status, _, raw = self.request("POST", "/api/trial/receipts", body, self.headers)
        self.assertEqual((status, json.loads(raw)["error"]), (429, "trial_daily"))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn(KEY, repr(self.snapshot()))
        self.assertNotIn(KEY, repr(self.byok.rows))
        self.assertNotIn(KEY, repr(self.ledger.usage()))

    def test_origin_auth_csrf_fields_and_owner_checks(self):
        body = json.dumps({"receipt_id": rid(1), "query": "昭和", "api_key": KEY, "max_cost_microusd": 100_000})
        for headers, expected in (({}, 403), ({"Origin": ORIGIN, "Content-Type": "application/json"}, 401),
                                  ({k: v for k, v in self.headers.items() if k != "X-CSRF-Token"}, 403)):
            self.assertEqual(self.request("POST", "/api/byok/receipts", body, headers)[0], expected)
        for extra in ({"owner": "other"}, {"mode": "trial"}, {"model": "other"}, {"url": "http://127.0.0.1"},
                      {"max_cost_microusd": True}, {"max_cost_microusd": 500_001}, {"api_key": "bad\nheader"}):
            self.assertEqual(self.submit(1, **extra)[0], 400)
        self.assertEqual(self.submit(1)[0], 201)
        token, session = self.login.boundary.issue_verified(ISSUER, "other-owner")
        other = {**self.headers, "Cookie": f"{COOKIE}={token}", "X-CSRF-Token": session.csrf}
        path = "/api/byok/receipts/" + rid(1)
        for method, suffix, body in (("GET", "", None), ("POST", "/cancel", "{}"), ("POST", "/received", "{}")):
            self.assertEqual(self.request(method, path + suffix, body, other)[0], 404)
        self.assertEqual(self.submit(1, query="別テーマ")[0], 409)
        self.assertEqual(self.submit(1, max_cost_microusd=50_000)[0], 409)
        self.assertEqual(self.request("POST", path + "/cancel", '{"api_key":"secret"}', self.headers)[0], 400)

    def test_concurrent_intake_and_rate_have_distinct_rejections(self):
        with ThreadPoolExecutor(8) as pool:
            replies = list(pool.map(self.submit, range(8)))
        self.assertEqual(sum(status == 201 for status, _, _ in replies), 1)
        for status, _, raw in replies:
            if status != 201:
                self.assertEqual((status, json.loads(raw)["error"]), (503, "server_busy"))
        self.byok.limits = replace(self.byok.limits, starts=1)
        self.assertEqual(json.loads(self.submit(99)[2])["error"], "request_rate")

    def test_restart_has_no_key_job_result_or_automatic_charge(self):
        self.assertEqual(self.submit(1)[0], 201)
        self.assertTrue(self.entered.wait(2))
        self.byok.stop()
        self.assertEqual(self.byok.rows, {})
        self.assertEqual(self.byok.running, {})
        replacement = ByokRuntime(limits(), slots=self.slots, generate=self.generate)
        self.server.byok = replacement
        with self.assertRaisesRegex(PublicError, "receipt_not_found"):
            replacement.receipt(self.owner, rid(1))
        self.assertEqual(len(self.calls), 1)
        replacement.stop()
        # Production restart also invalidates every old authentication session.
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        with self.assertRaisesRegex(PublicError, "authentication_required"):
            boundary.authorize({"Host": "timeline.example", **self.headers}, write=True)

    def test_result_acknowledgement_expiry_and_cancel_notice(self):
        self.submit(1)
        self.assertTrue(self.entered.wait(2))
        path = "/api/byok/receipts/" + rid(1)
        self.request("POST", path + "/cancel", "{}", self.headers)
        wait_for(lambda: not self.byok.running)
        value = json.loads(self.request("GET", path, headers=self.headers)[2])
        self.assertTrue(value["charge_may_continue"])
        self.release.set()
        self.submit(2)
        wait_for(lambda: not self.byok.running)
        path = "/api/byok/receipts/" + rid(2)
        self.assertEqual(self.request("POST", path + "/received", "{}", self.headers)[0], 200)
        self.byok.clock = lambda: 10**12
        self.assertEqual(self.request("GET", path, headers=self.headers)[0], 404)
        self.assertEqual(self.byok.rows, {})


class ConfigurationTests(unittest.TestCase):
    def test_all_limits_required_and_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "explicitly configured"):
                ByokLimits.from_env()
        for field, value in (("concurrent", 0), ("fetch_calls", 0), ("fetch_bytes", True),
                             ("time_limit", 3601), ("max_cost_microusd", 5_000_001)):
            with self.assertRaises(ValueError):
                limits(**{field: value})

    def test_combined_service_rejects_unshared_slots(self):
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        login = GoogleLogin(boundary, CLIENT, "offline-secret", exchange=lambda _: None)
        fake_trial = type("Runtime", (), {"ledger": None, "slots": None})()
        runtime = ByokRuntime(limits(), slots=GenerationSlots(1), generate=lambda *_: None)
        with self.assertRaisesRegex(ValueError, "share generation slots"):
            make_server(login, port=0, runtime=fake_trial, byok=runtime)
        runtime.stop()


if __name__ == "__main__":
    unittest.main()
