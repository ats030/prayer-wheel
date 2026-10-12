"""Loopback-only, token-protected bridge to the existing private Python API.

No model, DB or credentials are forwarded to a user-selected destination.
This service is not started automatically or exposed by the public deployment.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

UPSTREAM = "http://100.94.207.13:8532"
MAX_RESPONSE = 4 * 1024 * 1024


def allowed_route(method, target):
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment or target != parts.path + ("?" + parts.query if parts.query else ""):
        return False
    if parts.query:
        return method == "GET" and parts.path == "/api/jobs" and bool(re.fullmatch(r"offset=[0-9]{1,18}", parts.query))
    if method == "GET":
        return parts.path in {"/api/jobs", "/api/quality", "/api/health"} or bool(re.fullmatch(r"/api/jobs/[1-9][0-9]{0,17}", parts.path))
    return method == "POST" and (parts.path == "/api/jobs" or bool(re.fullmatch(
        r"/api/jobs/[1-9][0-9]{0,17}/(retry|regenerate|cancel|delete|milestones)", parts.path)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self):
        self.connection.settimeout(10)
        authorization = self.headers.get_all("Authorization", [])
        hosts = self.headers.get_all("Host", [])
        if len(authorization) != 1 or not hmac.compare_digest(
                authorization[0].encode(), ("Bearer " + self.server.gateway_token).encode()):
            return self.reply(403, {"error": "認証が必要です。"})
        if hosts != [f"127.0.0.1:{self.server.server_port}"]:
            return self.reply(403, {"error": "接続先が不正です。"})
        if not allowed_route(self.command, self.path):
            return self.reply(404, {"error": "APIが見つかりません。"})
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            return self.reply(400, {"error": "リクエスト形式が不正です。"})
        body = None
        if self.command == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 65536 if self.path.endswith("/milestones") else 2048
                if not 1 <= length <= limit:
                    return self.reply(413, {"error": "入力サイズが上限外です。"})
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    return self.reply(415, {"error": "JSON形式が必要です。"})
                body = self.rfile.read(length)
                if len(body) != length or not isinstance(json.loads(body), dict):
                    raise ValueError
            except (ValueError, OSError):
                return self.reply(400, {"error": "入力を読み取れませんでした。"})
        elif self.headers.get("Content-Length", "0") != "0":
            return self.reply(400, {"error": "GETに本文は指定できません。"})
        if not self.server.slots.acquire(blocking=False):
            return self.reply(429, {"error": "接続が混み合っています。"})
        try:
            # Fixed origin/headers. Browser cookies, JWTs and gateway token never reach the generator.
            headers = {"Host": urlsplit(self.server.upstream).netloc,
                       "Origin": self.server.upstream, "Content-Type": "application/json"}
            req = urllib.request.Request(self.server.upstream + self.path, data=body,
                                         method=self.command, headers=headers)
            try:
                response = self.server.opener.open(req, timeout=10)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                if not 200 <= response.code <= 599 or 300 <= response.code <= 399:
                    raise ValueError
                if response.headers.get_content_type() != "application/json":
                    raise ValueError
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError
                if isinstance(data.get("result"), dict):
                    data["result"].pop("trace", None)
                self.reply(response.code, data)
        except (ValueError, OSError, urllib.error.URLError):
            self.reply(502, {"error": "生成処理へ接続できませんでした。"})
        finally:
            self.server.slots.release()

    do_GET = handle_api
    do_POST = handle_api


def make_server(token, *, port=8535, upstream=UPSTREAM):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("A dedicated gateway token is required")
    # The test-only upstream override is also loopback-bound. No public URL or user input.
    if upstream != UPSTREAM and not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", upstream):
        raise ValueError("Only the fixed private API or loopback test API is allowed")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.gateway_token = token
    server.upstream = upstream
    server.slots = threading.BoundedSemaphore(4)
    server.opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    return server


def read_gateway_token(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 256:
        raise ValueError("Gateway token file must be private (600), regular and at most 256 bytes")
    token = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("Invalid gateway token")
    return token


if __name__ == "__main__":
    token_file = os.environ.get("TIMELINE_GATEWAY_TOKEN_FILE")
    if not token_file:
        raise SystemExit("TIMELINE_GATEWAY_TOKEN_FILE is required; no shared .env API key is used")
    try:
        token = read_gateway_token(token_file)
        make_server(token).serve_forever()
    except (ValueError, OSError):
        raise SystemExit("Private gateway could not start; check token file and loopback port") from None
