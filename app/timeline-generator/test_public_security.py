import copy
from datetime import datetime, timezone
from email.message import Message
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from public_security import COOKIE, PublicBoundary, PublicError, receipt_view, result_view
from trial import TrialLedger

ORIGIN = "https://timeline.example"
ISSUER = "https://accounts.google.com"
RECEIPT = "receipt_0000000001"


def result():
    return {"kind": "result", "theme": "昭和", "period": None, "source_mode": "wikipedia",
            "api_key": "secret", "owner": "private", "trace": {"sources": []}, "job_id": 123,
            "events": [{"year": 1964, "date": "1964年", "title": "東京オリンピック",
                        "description": "東京で開催された。", "quote": "保存用の原文引用", "id": 12,
                        "source": {"url": "https://ja.wikipedia.org/wiki/昭和", "title": "昭和", "context_heading": "戦後"}}]}


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER, clock=lambda: self.now)
        # Test fixture simulates the *server-side verified* provider callback.
        # It is not evidence of a real Google sign-in or a trusted client header.
        self.token, self.session = self.boundary.issue_verified(ISSUER, "google-sub-1")

    def headers(self, **changes):
        headers = {"Host": "timeline.example", "Cookie": f"{COOKIE}={self.token}",
                   "Origin": ORIGIN, "X-CSRF-Token": self.session.csrf}
        headers.update(changes)
        return {key: value for key, value in headers.items() if value is not None}

    def assert_code(self, status, code, call):
        with self.assertRaises(PublicError) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))

    def test_issuer_is_explicit_and_owner_is_stable_and_pseudonymous(self):
        _, another = self.boundary.issue_verified(ISSUER, "google-sub-1")
        _, other = self.boundary.issue_verified(ISSUER, "google-sub-2")
        self.assertEqual(another.owner, self.session.owner)
        self.assertNotEqual(other.owner, self.session.owner)
        self.assertNotIn("google-sub", self.session.owner)
        self.assert_code(401, "authentication_required", lambda: self.boundary.issue_verified("https://evil.example", "google-sub-1"))
        self.assertEqual(self.boundary.authorize(self.headers()).owner, self.session.owner)
        stored = list(self.boundary.sessions)
        self.assertNotIn(self.token, stored)

    def test_configured_origin_matches_browser_canonical_origin(self):
        boundary = PublicBoundary("https://TIMELINE.EXAMPLE:443/", b"x" * 32, ISSUER)
        token, session = boundary.issue_verified(ISSUER, "google-sub-1")
        self.assertEqual(boundary.origin, ORIGIN)
        self.assertEqual(boundary.host, "timeline.example")
        headers = self.headers(Cookie=f"{COOKIE}={token}", **{"X-CSRF-Token": session.csrf})
        self.assertEqual(boundary.authorize(headers, write=True), session)
        ipv6 = PublicBoundary("https://[::1]:443", b"x" * 32, ISSUER)
        self.assertEqual(ipv6.origin, "https://[::1]")

    def test_session_expiry_logout_and_restart(self):
        self.assertIn("Secure; HttpOnly; SameSite=Lax", self.boundary.cookie(self.token, 3600))
        self.assertIn("Path=/", self.boundary.cookie(self.token, 3600))
        self.now += 3600
        self.assert_code(401, "authentication_required", lambda: self.boundary.authorize(self.headers()))
        self.token, self.session = self.boundary.issue_verified(ISSUER, "google-sub-1")
        self.assertIn("Max-Age=0", self.boundary.logout(self.headers()))
        self.assert_code(401, "authentication_required", lambda: self.boundary.authorize(self.headers()))
        new = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.assert_code(401, "authentication_required", lambda: new.authorize(self.headers()))

    def test_session_view_does_not_expose_provider_subject_or_owner(self):
        view = self.boundary.session_view(self.headers())
        self.assertEqual(set(view), {"authenticated", "csrf_token", "expires_in"})
        self.assertEqual(view["expires_in"], 3600)
        self.assertNotIn(self.session.owner, json.dumps(view))

    def test_capacity_is_bounded_and_expired_sessions_release_capacity(self):
        small = PublicBoundary(ORIGIN, b"x" * 32, ISSUER, capacity=1, clock=lambda: self.now)
        small.issue_verified(ISSUER, "subject")
        self.assert_code(503, "session_capacity", lambda: small.issue_verified(ISSUER, "other"))
        self.now += 3600
        small.issue_verified(ISSUER, "other")
        self.assertEqual(len(small.sessions), 1)

    def test_capacity_is_atomic_under_parallel_callbacks(self):
        small = PublicBoundary(ORIGIN, b"x" * 32, ISSUER, capacity=3)
        successes = []
        def issue():
            try:
                successes.append(small.issue_verified(ISSUER, "subject"))
            except PublicError:
                pass
        threads = [threading.Thread(target=issue) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(successes), 3)

    def test_no_client_identity_header_can_mint_a_session(self):
        for cookie in (None, "", f"{COOKIE}=forged", f"{COOKIE}=" + "a" * 43,
                       f"{COOKIE}={self.token}; {COOKIE}={self.token}", "x=" + "a" * 8200):
            with self.subTest(cookie=cookie):
                self.assert_code(401, "authentication_required", lambda: self.boundary.authorize(
                    self.headers(Cookie=cookie, **{"X-Owner": self.session.owner, "X-User-Email": "owner@example.test"})))

    def test_origin_host_csrf_and_fetch_site(self):
        for host in (None, "evil.example", "127.0.0.1", "timeline.example.evil.test"):
            self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(self.headers(Host=host)))
        for origin in ("null", "https://evil.example", "http://timeline.example", ORIGIN + "/"):
            self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(self.headers(Origin=origin)))
        self.assertEqual(self.boundary.authorize(self.headers(Origin=None)).owner, self.session.owner)
        self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(self.headers(Origin=None), write=True))
        self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(self.headers(**{"Sec-Fetch-Site": "same-site"})))
        self.assert_code(403, "csrf_rejected", lambda: self.boundary.authorize(self.headers(**{"X-CSRF-Token": "wrong"}), write=True))
        self.assert_code(403, "csrf_rejected", lambda: self.boundary.authorize(self.headers(**{"X-CSRF-Token": "あ"}), write=True))
        self.boundary.authorize(self.headers(), write=True)
        self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(
            self.headers(Host="127.0.0.1", **{"X-Forwarded-Host": "timeline.example", "X-Forwarded-Proto": "https"})))

    def test_repeated_header_rejection(self):
        # The actual HTTP parser preserves duplicates; do not trust its first value.
        headers = Message()
        for key, value in self.headers().items():
            headers[key] = value
        headers["Origin"] = "https://evil.example"
        self.assert_code(403, "origin_rejected", lambda: self.boundary.authorize(headers))

    def test_public_startup_configuration_is_fail_closed(self):
        with patch.dict(os.environ, {"TIMELINE_SOURCE": "wikipedia", "TIMELINE_PUBLIC_ORIGIN": ORIGIN,
                                     "TIMELINE_PUBLIC_OWNER_KEY": "a" * 64}, clear=True):
            self.assertEqual(PublicBoundary.from_env(ISSUER).origin, ORIGIN)
            for mode in (None, "", "searxng"):
                if mode is None:
                    os.environ.pop("TIMELINE_SOURCE", None)
                else:
                    os.environ["TIMELINE_SOURCE"] = mode
                with self.assertRaises(ValueError):
                    PublicBoundary.from_env(ISSUER)
        for origin in ("", "http://timeline.example", "https://u:p@timeline.example", ORIGIN + "/path", ORIGIN + "?x=1", ORIGIN + "#x", ORIGIN + ":bad"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                PublicBoundary(origin, b"x" * 32, ISSUER)

    def test_projection_is_whitelisted_and_input_unchanged(self):
        original = result()
        before = copy.deepcopy(original)
        output = result_view(original)
        self.assertEqual(original, before)
        self.assertEqual(set(output), {"theme", "period", "source_mode", "notice", "events"})
        self.assertEqual(set(output["events"][0]), {"year", "date", "title", "description", "source"})
        self.assertEqual(set(output["events"][0]["source"]), {"url", "title"})
        serialized = json.dumps(output, ensure_ascii=False)
        for private in ("quote", "trace", "api_key", "owner", "job_id", "context_heading", "原文引用"):
            self.assertNotIn(private, serialized)

    def test_projection_refuses_unknown_route_and_malformed_results(self):
        for updates in ({"source_mode": None}, {"source_mode": "searxng"}, {"kind": "error"},
                        {"events": []}, {"events": result()["events"] * 51}, {"theme": "x" * 181}, {"notice": {}}, {"period": []}):
            value = {**result(), **updates}
            self.assert_code(502, "invalid_result", lambda: result_view(value))
        for value in (None, [], "string"):
            self.assert_code(502, "invalid_result", lambda: result_view(value))
        for updates in ({"year": True}, {"year": 1000001}, {"year": "1964"}, {"source": []}, {"date": None}, {"description": "x" * 4001}):
            value = result()
            value["events"][0].update(updates)
            self.assert_code(502, "invalid_result", lambda: result_view(value))

    def test_projection_rejects_credentials_foreign_hosts_and_unsafe_urls(self):
        for url in ("javascript:alert(1)", "http://ja.wikipedia.org/wiki/a", "https://evil.test/wiki/a",
                    "https://ja.wikipedia.org.evil.test/wiki/a", "https://ja.wikipedia.org:8443/wiki/a",
                    "https://user:secret@ja.wikipedia.org/wiki/a", "https://ja.wikipedia.org/wiki/",
                    "https://ja.wikipedia.org/wiki/a?api_key=secret", "https://ja.wikipedia.org/wiki/a%0aevil",
                    "https://ja.wikipedia.org/wiki/a\\evil", None):
            value = result()
            value["events"][0]["source"]["url"] = url
            self.assert_code(502, "invalid_result", lambda: result_view(value))
        value = result()
        value["events"][0]["source"]["url"] = "https://en.wikipedia.org/wiki/Sh%C5%8Dwa_era#History"
        self.assertEqual(len(result_view(value)["events"]), 1)

    def test_projection_rejects_aggregate_oversize(self):
        value = result()
        event = value["events"][0]
        event["description"] = "あ" * 4000
        value["events"] = [event] * 50
        self.assert_code(502, "invalid_result", lambda: result_view(value))


class HTTPBoundaryTests(unittest.TestCase):
    """Real HTTP transport + isolated trial DB; no Google or model requests."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = TrialLedger(Path(self.tmp.name) / "public-trial.sqlite3")
        self.boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.token, self.session = self.boundary.issue_verified(ISSUER, "owner")
        self.other_token, self.other_session = self.boundary.issue_verified(ISSUER, "other-owner")
        self.ledger.accept(self.session.owner, RECEIPT, "new", {"topic": "昭和", "api_key": "never-return"})
        boundary, ledger = self.boundary, self.ledger
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_api(self, cancel=False):
                try:
                    if not self.path.startswith("/api/receipts/"):
                        raise PublicError(404, "not_found")
                    output = boundary.receipt(ledger, self.headers, self.path.rsplit("/", 1)[1], cancel=cancel)
                    status = 200
                except PublicError as exc:
                    status, output = exc.status, {"error": exc.code}
                body = json.dumps(output, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                self.handle_api()
            def do_POST(self):
                self.handle_api(cancel=True)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.ledger.close()
        self.tmp.cleanup()

    def request(self, method="GET", receipt=RECEIPT, token=None, csrf=None, origin=ORIGIN):
        headers = {"Host": "timeline.example"}
        if token is not None:
            headers["Cookie"] = f"{COOKIE}={token}"
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        if origin is not None:
            headers["Origin"] = origin
        connection = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            connection.request(method, "/api/receipts/" + receipt, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_unauthenticated_and_other_owner_have_no_access(self):
        self.assertEqual(self.request()[0], 401)
        foreign = self.request(token=self.other_token)
        missing = self.request(token=self.other_token, receipt="missing_000000001")
        self.assertEqual(foreign, missing)
        self.assertEqual(foreign, (404, {"error": "receipt_not_found"}))
        rejected = self.request("POST", token=self.other_token, csrf=self.other_session.csrf)
        self.assertEqual(rejected[0], 404)
        self.assertEqual(self.ledger.get(self.session.owner, RECEIPT)["state"], "queued")

    def test_only_authenticated_owner_can_cancel_with_origin_and_csrf(self):
        self.assertEqual(self.request("POST", token=self.token)[0], 403)
        self.assertEqual(self.request("POST", token=self.token, csrf=self.session.csrf, origin=None)[0], 403)
        self.assertEqual(self.request("POST", token=self.token, csrf=self.session.csrf, origin="https://evil.example")[0], 403)
        self.assertEqual(self.ledger.get(self.session.owner, RECEIPT)["state"], "queued")
        status, output = self.request("POST", token=self.token, csrf=self.session.csrf)
        self.assertEqual((status, output["state"]), (200, "cancelled"))
        self.assertNotIn("owner", output)
        self.assertNotIn("payload", output)

    def test_completed_result_is_minimal_over_http(self):
        self.ledger.claim()
        self.ledger.finish(self.session.owner, RECEIPT, result())
        status, output = self.request(token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("expires_at", output)
        self.assertEqual(output["result"], result_view(result()))
        self.assertNotIn("private", json.dumps(output))
        self.assertNotIn("never-return", json.dumps(output))

    def test_completed_cancel_and_expired_result_have_safe_status_codes(self):
        self.ledger.claim()
        self.ledger.finish(self.session.owner, RECEIPT, result())
        self.assertEqual(self.request("POST", token=self.token, csrf=self.session.csrf),
                         (409, {"error": "receipt_state"}))
        self.ledger.clock = lambda: datetime(2099, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(self.request(token=self.token), (410, {"error": "receipt_gone"}))
        self.assertEqual(self.request(token=self.other_token), (404, {"error": "receipt_not_found"}))

    def test_invalid_result_fails_closed_over_http(self):
        self.ledger.claim()
        value = result()
        value["source_mode"] = "searxng"
        self.ledger.finish(self.session.owner, RECEIPT, value)
        self.assertEqual(self.request(token=self.token), (502, {"error": "invalid_result"}))


if __name__ == "__main__":
    unittest.main()
