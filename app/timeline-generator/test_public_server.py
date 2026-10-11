from http.client import HTTPConnection
import json
import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from google_login import GoogleLogin, ISSUER
from public_security import PublicBoundary, COOKIE
from public_server import make_server
from test_google_login import CLIENT, ORIGIN, jwt
from test_public_security import result
from trial import TrialLedger


class PublicServerTests(unittest.TestCase):
    def setUp(self):
        self.fields = []
        boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.login = GoogleLogin(boundary, CLIENT, "test-secret", exchange=self.exchange)
        self.server = make_server(self.login, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def exchange(self, fields):
        import time
        self.fields.append(fields)
        return jwt({"iss": ISSUER, "aud": CLIENT, "sub": "1234567890", "nonce": self.nonce,
                    "iat": int(time.time()), "exp": int(time.time()) + 3600})

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        merged = {"Host": "timeline.example", **(headers or {})}
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=merged)
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def start(self):
        status, headers, raw = self.request("POST", "/auth/google/start", "{}",
            {"Origin": ORIGIN, "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        url = json.loads(raw)["url"]
        params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        self.nonce = params["nonce"]
        cookie = next(value for key, value in headers if key == "Set-Cookie").split(";", 1)[0]
        return params, cookie

    def attach_ledger(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        ledger = TrialLedger(Path(directory.name) / "trial.sqlite3", clock=lambda: self.now)
        self.addCleanup(ledger.close)
        self.server.ledger = ledger
        token, session = self.login.boundary.issue_verified(ISSUER, "owner-one")
        headers = {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN,
                   "Content-Type": "application/json", "X-CSRF-Token": session.csrf}
        return ledger, session.owner, headers

    def test_receipt_http_ownership_csrf_and_cancel_refund(self):
        ledger, owner, headers = self.attach_ledger()
        receipt_id = "owned-receipt-0001"
        ledger.accept(owner, receipt_id, "new", {"theme": "private input"})
        path = "/api/receipts/" + receipt_id
        self.assertEqual(self.request("GET", path)[0], 401)
        token, other = self.login.boundary.issue_verified(ISSUER, "owner-two")
        other_headers = {**headers, "Cookie": f"{COOKIE}={token}", "X-CSRF-Token": other.csrf}
        for method, suffix, body in (("GET", "", None), ("POST", "/cancel", "{}"), ("POST", "/received", "{}")):
            self.assertEqual(self.request(method, path + suffix, body, other_headers)[0], 404)
        status, _, raw = self.request("GET", path, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(raw)), {"receipt_id", "state", "accepted_at", "updated_at"})
        self.assertNotIn(b"private input", raw)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", {k: v for k, v in headers.items() if k != "X-CSRF-Token"})[0], 403)
        self.assertEqual(ledger.usage()["used"], 1)
        self.assertEqual(self.request("POST", path + "/cancel", '{"owner":"someone"}', headers)[0], 400)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", headers)[0], 200)
        self.assertEqual(ledger.usage()["used"], 0)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", headers)[0], 200)
        self.assertEqual(ledger.usage()["used"], 0)
        for suffix in ("/cancel", "/received"):
            self.assertEqual(self.request("GET", path + suffix, headers=headers)[0], 405)
        self.assertEqual(self.request("POST", "/api/receipts", "{}", headers)[0], 404)

    def test_result_receive_is_minimal_idempotent_and_expires(self):
        ledger, owner, headers = self.attach_ledger()
        receipt_id = "owned-receipt-0002"
        ledger.accept(owner, receipt_id, "new", {"theme": "history"})
        ledger.claim()
        ledger.finish(owner, receipt_id, result())
        path = "/api/receipts/" + receipt_id
        status, _, raw = self.request("GET", path, headers=headers)
        self.assertEqual(status, 200)
        self.assertNotIn(b'"quote"', raw)
        self.assertNotIn(b'"trace"', raw)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", headers)[0], 409)
        status, _, raw = self.request("POST", path + "/received", "{}", headers)
        received = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(set(received), {"receipt_id", "expires_at", "received_at"})
        self.assertEqual(datetime.fromisoformat(received["expires_at"]), self.now + timedelta(minutes=10))
        self.assertEqual(self.request("POST", path + "/received", "{}", headers)[2], raw)
        self.now += timedelta(minutes=10)
        for method, suffix, body in (("GET", "", None), ("POST", "/received", "{}")):
            self.assertEqual(self.request(method, path + suffix, body, headers)[0], 410)

    def test_received_state_and_disabled_receipt_backend(self):
        ledger, owner, headers = self.attach_ledger()
        receipt_id = "owned-receipt-0003"
        ledger.accept(owner, receipt_id, "new", {})
        path = "/api/receipts/" + receipt_id
        self.assertEqual(self.request("POST", path + "/received", "{}", headers)[0], 409)
        self.assertEqual(ledger.get(owner, receipt_id)["state"], "queued")
        self.server.ledger = None
        self.assertEqual(self.request("GET", path, headers=headers)[0], 404)
        self.assertEqual(self.request("POST", path + "/cancel", "{}", headers)[0], 404)

    def test_full_http_login_and_logout_no_generation_routes(self):
        self.assertEqual(self.request("GET", "/api/session")[0], 401)
        params, pending = self.start()
        path = "/auth/google/callback?" + urlencode({"state": params["state"], "code": "code"})
        status, headers, body = self.request("GET", path, headers={"Cookie": pending, "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 303)
        self.assertIn(("Location", "/login"), headers)
        cookies = [value for key, value in headers if key == "Set-Cookie"]
        session_cookie = next(value for value in cookies if value.startswith(COOKIE + "=")).split(";", 1)[0]
        status, headers, raw = self.request("GET", "/api/session", headers={"Cookie": session_cookie})
        self.assertEqual(status, 200)
        session = json.loads(raw)
        self.assertEqual(set(session), {"authenticated", "csrf_token", "expires_in"})
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertIn(("Referrer-Policy", "no-referrer"), headers)
        self.assertEqual(self.request("POST", "/auth/logout", "{}", {"Cookie": session_cookie, "Origin": ORIGIN, "Content-Type": "application/json"})[0], 403)
        status, _, raw = self.request("POST", "/auth/logout", "{}", {"Cookie": session_cookie,
            "Origin": ORIGIN, "Content-Type": "application/json", "X-CSRF-Token": session["csrf_token"]})
        self.assertEqual((status, json.loads(raw)), (200, {"authenticated": False}))
        self.assertEqual(self.request("GET", "/api/session", headers={"Cookie": session_cookie})[0], 401)
        for path in ("/api/jobs", "/api/quality", "/api/receipts", "/data/timelines.sqlite3", "/.env", "/server.py"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("POST", "/api/jobs", "{}", {"Origin": ORIGIN})[0], 404)
        self.assertEqual(self.request("POST", "/api/trial/receipts", "{}", {"Origin": ORIGIN})[0], 404)

    def test_failure_redirect_does_not_echo_credentials_or_state(self):
        params, pending = self.start()
        status, headers, raw = self.request("GET", "/auth/google/callback?" + urlencode(
            {"state": params["state"], "error": "access_denied", "code": "secret-code"}), headers={"Cookie": pending})
        self.assertEqual(status, 303)
        self.assertIn(("Location", "/login?error=cancelled"), headers)
        self.assertNotIn(params["state"], str(headers))
        self.assertNotIn("secret-code", str(headers))
        self.assertEqual(self.fields, [])
        self.assertEqual(len(self.login.boundary.sessions), 0)

    def test_start_method_origin_and_body_limits(self):
        self.assertEqual(self.request("GET", "/auth/google/start")[0], 405)
        self.assertEqual(self.request("POST", "/auth/google/start", "{}")[0], 403)
        for body, mime, status in (("owner=someone", "text/plain", 415),
                                  ('{"owner":"someone"}', "application/json", 400),
                                  ("x" * 4097, "application/json", 400),
                                  ("not-json", "application/json", 400)):
            self.assertEqual(self.request("POST", "/auth/google/start", body,
                {"Origin": ORIGIN, "Content-Type": mime})[0], status)
        self.assertEqual(len(self.login.pending), 0)
        self.assertEqual(self.request("GET", "/", headers={"Host": "evil.example"})[0], 403)

    def test_only_public_assets_and_loopback_backend(self):
        status, headers, raw = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn(b'data-site="timeline-generator"', raw)
        self.assertNotIn(b'/app.js', raw)
        self.assertIn(("X-Frame-Options", "DENY"), headers)
        self.assertTrue(any(key == "Content-Security-Policy" and "frame-ancestors 'none'" in value for key, value in headers))
        with self.assertRaises(ValueError):
            make_server(self.login, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
