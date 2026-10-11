"""HTTP frequency and byte-budget checks, using local fixtures only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest

from google_login import GoogleLogin, ISSUER
from public_limits import BudgetExceeded, PublicLimits
from public_security import PublicBoundary, COOKIE, receipt_view
from public_server import make_server
from test_google_login import CLIENT, ORIGIN
import test_public_server
from trial import TrialLedger


class LimitsTests(unittest.TestCase):
    def test_concurrent_requests_and_bytes_are_atomic(self):
        limits = PublicLimits(requests=10, total_bytes=10, owner_bytes=10, clock=lambda: 0)
        def attempt(number):
            try:
                limits.check_request()
                return "accepted"
            except BudgetExceeded as exc:
                return exc.code
        with ThreadPoolExecutor(20) as pool:
            outcomes = list(pool.map(attempt, range(20)))
        self.assertEqual(outcomes.count("accepted"), 10)
        def response(number):
            try:
                limits.check_response(str(number), 1)
                return "accepted"
            except BudgetExceeded as exc:
                return exc.code
        with ThreadPoolExecutor(20) as pool:
            outcomes = list(pool.map(response, range(20)))
        self.assertEqual(outcomes.count("accepted"), 10)
        self.assertEqual(outcomes.count("response_budget"), 10)

    def test_bounded_owner_cache_and_window_expiry(self):
        now = [0]
        limits = PublicLimits(owners=1, reads=1, clock=lambda: now[0])
        limits.check_owner("one")
        for owner in ("one", "two"):
            with self.assertRaises(BudgetExceeded) as caught:
                limits.check_owner(owner)
            self.assertEqual(caught.exception.retry_after, 60)
        self.assertEqual(len(limits.people), 1)
        now[0] = 60
        limits.check_owner("two")
        self.assertEqual(set(limits.people), {"two"})
        with self.assertRaises(ValueError):
            PublicLimits(reads=0)


class LimitsHTTPTests(unittest.TestCase):
    request = test_public_server.PublicServerTests.request

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = TrialLedger(Path(self.temp.name) / "trial.sqlite3")
        self.now = 0
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.login = GoogleLogin(boundary, CLIENT, "test-secret", exchange=lambda _: None)
        self.headers, self.owner = self.identity("one")
        self.server = make_server(self.login, ledger=self.ledger, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.ledger.close()
        self.temp.cleanup()

    def identity(self, subject):
        token, session = self.login.boundary.issue_verified(ISSUER, subject)
        return {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN, "Content-Type": "application/json",
                "X-CSRF-Token": session.csrf}, session.owner

    def test_write_rate_does_not_refund_or_bypass_with_relogin(self):
        self.server.limits = PublicLimits(writes=1, clock=lambda: self.now)
        for identifier in ("receipt-owned-0001", "receipt-owned-0002"):
            self.ledger.accept(self.owner, identifier, "new", {})
        first = "/api/receipts/receipt-owned-0001/cancel"
        second = "/api/receipts/receipt-owned-0002/cancel"
        self.assertEqual(self.request("POST", first, "{}", self.headers)[0], 200)
        self.assertEqual(self.ledger.usage()["used"], 1)
        replacement, _ = self.identity("one")
        status, headers, raw = self.request("POST", second, "{}", {**replacement, "X-Owner": "other"})
        self.assertEqual((status, json.loads(raw)), (429, {"error": "request_rate"}))
        self.assertIn(("Retry-After", "60"), headers)
        self.assertEqual(self.ledger.get(self.owner, "receipt-owned-0002")["state"], "queued")
        self.assertEqual(self.ledger.usage()["used"], 1)
        self.now = 60
        self.assertEqual(self.request("POST", second, "{}", replacement)[0], 200)
        self.assertEqual(self.ledger.usage()["used"], 0)

    def test_read_rate_and_response_budget_are_separate_from_ai_quota(self):
        identifier = "receipt-owned-0001"
        row, _ = self.ledger.accept(self.owner, identifier, "new", {})
        path = "/api/receipts/" + identifier
        self.server.limits = PublicLimits(reads=1, clock=lambda: self.now)
        self.assertEqual(self.request("GET", path, headers=self.headers)[0], 200)
        self.assertEqual(self.request("GET", path, headers=self.headers)[0], 429)
        length = len(json.dumps(receipt_view(row), ensure_ascii=False).encode())
        self.server.limits = PublicLimits(owner_bytes=length, total_bytes=length * 2, clock=lambda: self.now)
        self.assertEqual(self.request("GET", path, headers=self.headers)[0], 200)
        status, headers, raw = self.request("GET", path, headers=self.headers)
        self.assertEqual((status, json.loads(raw)), (429, {"error": "response_budget"}))
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertIn(("Retry-After", "60"), headers)
        self.assertEqual(self.ledger.usage()["used"], 1)

    def test_global_and_login_start_budgets(self):
        self.server.limits = PublicLimits(requests=1, clock=lambda: self.now)
        self.assertEqual(self.request("GET", "/login")[0], 200)
        self.assertEqual(self.request("GET", "/unknown")[0], 429)
        self.assertEqual(self.request("HEAD", "/login")[0], 429)
        self.server.limits = PublicLimits(starts=1, clock=lambda: self.now)
        self.assertEqual(self.request("POST", "/auth/google/start", "{}", self.headers)[0], 200)
        self.assertEqual(self.request("POST", "/auth/google/start", "{}", self.headers)[0], 429)
        self.assertEqual(len(self.login.pending), 1)


if __name__ == "__main__":
    unittest.main()
