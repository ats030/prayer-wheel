import base64
from email.message import Message
import hashlib
import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit

import google_login
from google_login import GoogleLogin, ISSUER, LOGIN_COOKIE, AUTHORIZE, TOKEN_ENDPOINT
from public_security import PublicBoundary, PublicError, COOKIE

ORIGIN = "https://timeline.example"
CLIENT = "123-test.apps.googleusercontent.com"


def jwt(claims, header=None):
    def segment(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    # Offline fixture, NOT a signed Google token. Production token provenance
    # is tested separately at the pinned TLS transport seam below.
    return segment(header or {"alg": "RS256"}) + "." + segment(claims) + ".fixture_signature"


class GoogleLoginTests(unittest.TestCase):
    def setUp(self):
        self.now, self.wall = 1000, 1700000000
        self.boundary = PublicBoundary(ORIGIN, b"x" * 32, ISSUER)
        self.fields, self.claim_changes = [], {}
        self.login = GoogleLogin(self.boundary, CLIENT, "test-secret", exchange=self.exchange,
                                 clock=lambda: self.now, wall_clock=lambda: self.wall)

    def exchange(self, fields):
        self.fields.append(fields)
        return jwt(self.claims)

    def headers(self, cookie=None, origin=ORIGIN):
        headers = {"Host": "timeline.example", "Sec-Fetch-Site": "same-origin"}
        if cookie is not None:
            headers["Cookie"] = cookie
        if origin is not None:
            headers["Origin"] = origin
        return headers

    def begin(self):
        url, cookie = self.login.begin(self.headers())
        self.params = {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}
        self.binding = cookie.split(";", 1)[0]
        self.claims = {"iss": ISSUER, "aud": CLIENT, "sub": "1234567890", "nonce": self.params["nonce"],
                       "iat": self.wall, "exp": self.wall + 3600, "email": "never-store@example.test"}
        return url, cookie

    def finish(self, **changes):
        params = {"state": self.params["state"], "code": "authorization-code", **changes}
        headers = self.headers(self.binding, origin=None)
        headers["Sec-Fetch-Site"] = "cross-site"
        return self.login.finish(headers, urlencode(params))

    def assert_error(self, status, code, call):
        with self.assertRaises(PublicError) as caught:
            call()
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))

    def test_start_is_minimal_and_browser_bound_with_pkce(self):
        url, cookie = self.begin()
        self.assertTrue(url.startswith(AUTHORIZE + "?"))
        self.assertEqual(self.params["scope"], "openid")
        self.assertEqual(self.params["access_type"], "online")
        self.assertEqual(self.params["redirect_uri"], ORIGIN + "/auth/google/callback")
        self.assertNotIn("test-secret", url)
        self.assertIn("Secure; HttpOnly; SameSite=Lax; Max-Age=600", cookie)
        self.assertNotEqual(self.params["state"], self.binding.split("=", 1)[1])
        cookies = self.finish()
        expected = base64.urlsafe_b64encode(hashlib.sha256(self.fields[0]["code_verifier"].encode()).digest()).decode().rstrip("=")
        self.assertEqual(self.params["code_challenge"], expected)
        self.assertEqual(self.fields[0]["grant_type"], "authorization_code")
        self.assertEqual(self.fields[0]["redirect_uri"], self.params["redirect_uri"])
        self.assertIn(f"{COOKIE}=", cookies[0])
        self.assertIn("Max-Age=0", cookies[1])
        self.assertEqual(len(self.boundary.sessions), 1)
        serialized = repr(self.boundary.sessions)
        self.assertNotIn("never-store", serialized)
        self.assertNotIn("1234567890", serialized)

    def test_callback_is_single_use_even_on_parallel_requests(self):
        self.begin()
        results = []
        def call():
            try:
                results.append(self.finish())
            except PublicError as exc:
                results.append(exc.code)
        threads = [threading.Thread(target=call) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.fields), 1)
        self.assertEqual(len(self.boundary.sessions), 1)
        self.assertEqual(results.count("login_state"), 9)

    def test_wrong_binding_does_not_consume_legitimate_login(self):
        self.begin()
        query = urlencode({"state": self.params["state"], "code": "code"})
        for cookie in (None, f"{LOGIN_COOKIE}=" + "a" * 43, self.binding + "; " + self.binding):
            self.assert_error(403, "login_state", lambda: self.login.finish(self.headers(cookie), query))
        self.assertEqual(len(self.fields), 0)
        self.finish()
        self.assertEqual(len(self.fields), 1)

    def test_start_rejects_cross_origin_and_callback_rejects_foreign_host(self):
        self.assert_error(403, "origin_rejected", lambda: self.login.begin(self.headers(origin=None)))
        self.assert_error(403, "origin_rejected", lambda: self.login.begin(self.headers(origin="https://evil.example")))
        self.begin()
        headers = self.headers(self.binding)
        headers["Host"] = "evil.example"
        self.assert_error(403, "login_state", lambda: self.login.finish(headers, "state=" + self.params["state"]))
        headers = Message()
        for key, value in self.headers(self.binding).items():
            headers[key] = value
        headers["Cookie"] = self.binding
        self.assert_error(403, "login_state", lambda: self.login.finish(headers, "state=" + self.params["state"]))

    def test_expiry_restart_and_pending_capacity(self):
        self.begin()
        self.now += 600
        self.assert_error(403, "login_state", self.finish)
        self.begin()
        empty = GoogleLogin(self.boundary, CLIENT, "test-secret", exchange=self.exchange)
        self.assert_error(403, "login_state", lambda: empty.finish(self.headers(self.binding), urlencode({"state": self.params["state"], "code": "code"})))
        self.login.capacity = 1
        self.assert_error(503, "login_capacity", lambda: self.login.begin(self.headers()))
        self.now += 600
        self.begin()
        self.assertEqual(len(self.login.pending), 1)

    def test_denial_consumes_state_without_exchanging_code(self):
        self.begin()
        self.assert_error(401, "login_cancelled", lambda: self.finish(error="access_denied"))
        self.assert_error(403, "login_state", self.finish)
        self.assertEqual(len(self.fields), 0)

    def test_browser_id_token_is_never_used(self):
        self.begin()
        self.assert_error(403, "login_state", lambda: self.finish(code="", id_token=jwt(self.claims)))
        self.assertEqual(len(self.fields), 0)
        self.assertEqual(len(self.boundary.sessions), 0)

    def test_invalid_claims_never_issue_a_session(self):
        changes = ({"iss": "https://evil.example"}, {"aud": "other-client"}, {"aud": [CLIENT]},
                   {"azp": "other-client"}, {"exp": self.wall}, {"exp": "later"}, {"exp": True},
                   {"iat": self.wall + 61}, {"iat": None}, {"nonce": "wrong"}, {"sub": ""},
                   {"sub": "x" * 256}, {"sub": 123}, {"sub": "日本語"}, {"nbf": self.wall + 1}, {"nbf": True})
        for change in changes:
            with self.subTest(change=change):
                self.begin()
                self.claims.update(change)
                self.assert_error(401, "login_failed", self.finish)
                self.assertEqual(len(self.boundary.sessions), 0)

    def test_invalid_jwt_format_and_alg_are_rejected(self):
        for token in ("", "x", "a.a.a", "e30.e30.a", "a." + "x" * 20000 + ".a", jwt({}, {"alg": "none"})):
            self.begin()
            self.login.exchange = lambda fields: token
            self.assert_error(401, "login_failed", self.finish)
        self.assertEqual(len(self.boundary.sessions), 0)

    def test_query_ambiguity_and_transport_failure_do_not_issue(self):
        self.begin()
        query = urlencode({"state": self.params["state"], "code": "one"}) + "&code=two"
        self.assert_error(403, "login_state", lambda: self.login.finish(self.headers(self.binding), query))
        def fail(fields):
            raise PublicError(502, "google_unavailable")
        self.login.exchange = fail
        self.assert_error(502, "google_unavailable", self.finish)
        self.assert_error(403, "login_state", self.finish)
        self.assertEqual(len(self.boundary.sessions), 0)

    def test_reauthentication_rotates_old_session(self):
        self.boundary.capacity = 1
        old, _ = self.boundary.issue_verified(ISSUER, "1234567890")
        self.begin()
        self.binding += f"; {COOKIE}={old}"
        cookies = self.finish()
        self.assertEqual(len(self.boundary.sessions), 1)
        self.assertNotIn(hashlib.sha256(old.encode()).digest(), self.boundary.sessions)
        self.assertNotIn(old, cookies[0])

    def test_failed_reauthentication_preserves_old_session(self):
        old, _ = self.boundary.issue_verified(ISSUER, "1234567890")
        self.begin()
        self.binding += f"; {COOKIE}={old}"
        self.claims["nonce"] = "wrong"
        self.assert_error(401, "login_failed", self.finish)
        self.assertIn(hashlib.sha256(old.encode()).digest(), self.boundary.sessions)

    def test_unconfigured_or_unreviewed_startup_fails(self):
        config = {"TIMELINE_SOURCE": "wikipedia", "TIMELINE_PUBLIC_ORIGIN": ORIGIN,
                  "TIMELINE_PUBLIC_OWNER_KEY": "a" * 64, "TIMELINE_GOOGLE_CLIENT_ID": CLIENT,
                  "TIMELINE_GOOGLE_CLIENT_SECRET": "test-secret", "TIMELINE_GOOGLE_CLIENT_REVIEWED": "1"}
        with patch.dict(os.environ, config, clear=True):
            self.assertEqual(GoogleLogin.from_env().redirect_uri, ORIGIN + "/auth/google/callback")
            for name in config:
                with patch.dict(os.environ, {name: ""}):
                    with self.assertRaises(ValueError):
                        GoogleLogin.from_env()
        with self.assertRaises(ValueError):
            GoogleLogin(self.boundary, "https://evil.example", "test-secret")


class GoogleTransportTests(unittest.TestCase):
    def test_fixed_endpoint_no_proxy_no_redirect_and_secret_only_in_post_body(self):
        class Response:
            status = 200
            def geturl(self):
                return TOKEN_ENDPOINT
            def read(self, limit):
                return b'{"id_token":"server-token","access_token":"discard-me"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        class Opener:
            def open(inner, request, timeout):
                self.assertEqual(request.full_url, TOKEN_ENDPOINT)
                self.assertEqual(request.get_method(), "POST")
                self.assertNotIn("secret", request.full_url)
                self.assertIn(b"client_secret=secret", request.data)
                self.assertEqual(timeout, 10)
                return Response()
        def build(*handlers):
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], google_login.HTTPSHandler)
            self.assertIsInstance(handlers[2], google_login.NoRedirect)
            self.assertIsNone(handlers[2].redirect_request(None, None, 302, "", {}, "https://evil.example"))
            return Opener()
        with patch.object(google_login, "build_opener", side_effect=build):
            self.assertEqual(google_login.google_exchange({"client_secret": "secret"}), "server-token")

    def test_provider_errors_are_sanitized(self):
        for exc in (URLError("client_secret=secret"), HTTPError(TOKEN_ENDPOINT, 400, "secret", {}, None), TimeoutError("secret")):
            with self.subTest(exc=type(exc).__name__), patch.object(google_login, "build_opener") as build:
                build.return_value.open.side_effect = exc
                with self.assertRaises(PublicError) as caught:
                    google_login.google_exchange({"client_secret": "secret"})
                self.assertEqual((caught.exception.status, str(caught.exception)), (502, "google_unavailable"))


if __name__ == "__main__":
    unittest.main()
