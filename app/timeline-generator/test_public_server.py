from http.client import HTTPConnection
import json
import threading
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from google_login import GoogleLogin, ISSUER
from public_security import PublicBoundary, COOKIE
from public_server import make_server
from test_google_login import CLIENT, ORIGIN, jwt


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
