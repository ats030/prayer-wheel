#!/usr/bin/env python3
"""Expose a local Ollama-compatible endpoint backed by Open WebUI."""

from __future__ import annotations

import json
import ipaddress
import os
import signal
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


load_dotenv(Path.home() / ".env")

LISTEN_HOST = env("OLLAMA_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(env("OLLAMA_PROXY_PORT", "11434"))
OPENWEBUI_BASE_URL = env("OPENWEBUI_BASE_URL").rstrip("/")
OPENWEBUI_API_KEY = env("OPENWEBUI_API_KEY")
TARGET_BASE_URL = env("OLLAMA_PROXY_TARGET_URL") or (
    f"{OPENWEBUI_BASE_URL}/ollama" if OPENWEBUI_BASE_URL else ""
)
TARGET_BASE_URL = TARGET_BASE_URL.rstrip("/")
REQUEST_TIMEOUT = int(env("OLLAMA_PROXY_TIMEOUT", "600"))
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(value.strip())
    for value in env("OLLAMA_PROXY_ALLOWED_NETWORKS", "127.0.0.0/8").split(",")
    if value.strip()
)
ALLOWED_ORIGINS = {
    value.strip()
    for value in env("OLLAMA_PROXY_ALLOWED_ORIGINS").split(",")
    if value.strip()
}


def require_config() -> None:
    missing = []
    if not TARGET_BASE_URL:
        missing.append("OPENWEBUI_BASE_URL or OLLAMA_PROXY_TARGET_URL")
    if not OPENWEBUI_API_KEY:
        missing.append("OPENWEBUI_API_KEY")
    if missing:
        raise SystemExit("Missing required config: " + ", ".join(missing))


def json_error(message: str) -> bytes:
    return json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "OllamaOpenWebUIProxy/1.0"

    def do_GET(self) -> None:  # noqa: N802
        self.forward()

    def do_POST(self) -> None:  # noqa: N802
        self.forward()

    def do_PUT(self) -> None:  # noqa: N802
        self.forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self.forward()

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self.request_allowed():
            return
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def request_allowed(self) -> bool:
        client = ipaddress.ip_address(self.client_address[0])
        origin = self.headers.get("Origin", "")
        if not any(client in network for network in ALLOWED_NETWORKS):
            self.send_error(403, "Client network is not allowed")
            return False
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_error(403, "Origin is not allowed")
            return False
        if not client.is_loopback and not origin:
            self.send_error(403, "Browser origin is required from LAN")
            return False
        browser_routes = {("GET", "/api/tags"), ("POST", "/api/show"), ("POST", "/api/chat"), ("OPTIONS", self.path)}
        if not client.is_loopback and (self.command, self.path) not in browser_routes:
            self.send_error(403, "Route is not allowed from LAN")
            return False
        return True

    def forward(self) -> None:
        if not self.request_allowed():
            return
        target_url = TARGET_BASE_URL + self.path
        request = urllib.request.Request(
            target_url,
            data=self.read_body(),
            headers=self.forward_headers(),
            method=self.command,
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                self.send_response(response.status)
                self.copy_response_headers(response.headers.items())
                self.end_headers()
                self.copy_body(response)
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            self.copy_response_headers(exc.headers.items())
            self.end_headers()
            self.copy_body(exc)
        except urllib.error.URLError as exc:
            payload = json_error(f"Upstream Ollama proxy is unavailable: {exc.reason}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def read_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else None

    def forward_headers(self) -> dict[str, str]:
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        headers["Authorization"] = f"Bearer {OPENWEBUI_API_KEY}"
        headers.setdefault("Accept", "application/json")
        return headers

    def copy_response_headers(self, items) -> None:
        for key, value in items:
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower in {"server", "date", "content-length"}:
                continue
            self.send_header(key, value)

    def copy_body(self, response) -> None:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )


def main() -> None:
    require_config()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)

    def shutdown(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(
        f"Serving Ollama-compatible proxy on http://{LISTEN_HOST}:{LISTEN_PORT} "
        f"-> {TARGET_BASE_URL}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
