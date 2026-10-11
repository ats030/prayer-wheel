#!/usr/bin/env python3
"""Isolated public authentication HTTP service; no private DB or generation worker."""
import json
import os
import re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from google_login import GoogleLogin, CALLBACK
from public_security import PublicError

ROOT = Path(__file__).resolve().parent
ASSETS = {"/": ("public-login.html", "text/html; charset=utf-8"),
          "/login": ("public-login.html", "text/html; charset=utf-8"),
          "/public-login.js": ("public-login.js", "text/javascript; charset=utf-8"),
          "/public-login.css": ("public-login.css", "text/css; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/tokens.css": ("tokens.css", "text/css; charset=utf-8"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}
RECEIPT_ROUTE = re.compile(r"/api/receipts/([A-Za-z0-9_-]{16,64})(?:/(cancel|received))?")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        # In particular, do not log callback query strings, codes or cookies.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, status, data, mime="application/json; charset=utf-8", cookies=(), location=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        for name, value in (("Content-Type", mime), ("Content-Length", str(len(body))),
                            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                            ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                            ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")):
            self.send_header(name, value)
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        if location:
            self.send_header("Location", location)
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def json_body(self):
        # No chunked/ambiguous bodies, no unbounded reads or client configuration.
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1:
            raise PublicError(400, "invalid_request")
        if self.headers.get_content_type() != "application/json":
            raise PublicError(415, "json_required")
        try:
            length = int(lengths[0])
            if not 1 <= length <= 4096:
                raise ValueError
            value = json.loads(self.rfile.read(length))
            if value != {}:
                raise ValueError
        except (ValueError, UnicodeError):
            raise PublicError(400, "invalid_request") from None

    def do_GET(self):
        login = self.server.login
        path = urlsplit(self.path).path
        try:
            if path == CALLBACK:
                try:
                    cookies = login.finish(self.headers, urlsplit(self.path).query)
                except PublicError as exc:
                    # No code/state/provider body ever reaches the landing URL.
                    error = "cancelled" if exc.code == "login_cancelled" else "unavailable" if exc.code == "google_unavailable" else "failed"
                    return self.reply(303, {}, location="/login?error=" + error)
                return self.reply(303, {}, cookies=cookies, location="/login")
            login.boundary.check_origin(self.headers)
            if path in ASSETS:
                name, mime = ASSETS[path]
                return self.reply(200, (ROOT / name).read_bytes(), mime)
            if path == "/api/session":
                return self.reply(200, login.boundary.session_view(self.headers))
            route = RECEIPT_ROUTE.fullmatch(path)
            if route and self.server.ledger is not None:
                if route[2]:
                    return self.reply(405, {"error": "post_required"})
                return self.reply(200, login.boundary.receipt(self.server.ledger, self.headers, route[1]))
            if path in ("/auth/google/start", "/auth/logout"):
                return self.reply(405, {"error": "post_required"})
            return self.reply(404, {"error": "not_found"})
        except PublicError as exc:
            return self.reply(exc.status, {"error": exc.code})

    def do_POST(self):
        login = self.server.login
        path = urlsplit(self.path).path
        try:
            login.boundary.check_origin(self.headers, write=True)
            route = RECEIPT_ROUTE.fullmatch(path)
            if route and route[2] and self.server.ledger is not None:
                # Authenticate before reading input; owner/configuration cannot come from the client.
                login.boundary.authorize(self.headers, write=True)
                self.json_body()
                if route[2] == "cancel":
                    result = login.boundary.receipt(self.server.ledger, self.headers, route[1], cancel=True)
                else:
                    result = login.boundary.receive(self.server.ledger, self.headers, route[1])
                return self.reply(200, result)
            if path not in ("/auth/google/start", "/auth/logout"):
                return self.reply(404, {"error": "not_found"})
            self.json_body()
            if path == "/auth/google/start":
                url, cookie = login.begin(self.headers)
                return self.reply(200, {"url": url}, cookies=(cookie,))
            cookie = login.boundary.logout(self.headers)
            return self.reply(200, {"authenticated": False}, cookies=(cookie,))
        except PublicError as exc:
            return self.reply(exc.status, {"error": exc.code})


def make_server(login, host="127.0.0.1", port=8534, *, ledger=None):
    # Deliberately loopback-only. Public TLS/reverse-proxy configuration is a
    # separate deployment prerequisite, not trusted X-Forwarded-* headers.
    if host != "127.0.0.1":
        raise ValueError("Public authentication backend must bind loopback only")
    server = ThreadingHTTPServer((host, port), Handler)
    server.login = login
    server.ledger = ledger
    return server


def main():
    try:
        login = GoogleLogin.from_env()
        server = make_server(login, port=int(os.environ.get("TIMELINE_PUBLIC_PORT", "8534")))
    except (ValueError, OSError) as exc:
        # Configuration errors contain fixed messages, not secret values.
        raise SystemExit("Public authentication startup refused: " + str(exc))
    with server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
