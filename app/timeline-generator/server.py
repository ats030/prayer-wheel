#!/usr/bin/env python3
"""Private HTTP application; no saved searches, cookies, or paid APIs."""
import json
import multiprocessing
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from timeline import TIME_LIMIT, TimelineError, build_timeline, parse_query

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("TIMELINE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TIMELINE_PORT", "8532"))
SLOT = threading.BoundedSemaphore(1)
REQUEST_TIME_LIMIT = TIME_LIMIT
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"), "/changelog": ("changelog.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/tokens.css": ("tokens.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}


def pipeline_worker(query, connection):
    """One disposable process makes DNS, slow HTTP bodies and model calls cancellable."""
    try:
        connection.send(build_timeline(query, connection.send))
    except TimelineError as exc:
        connection.send({"kind": "error", "message": str(exc)})
    except Exception:
        connection.send({"kind": "error", "message": "処理を完了できませんでした。条件を変えて再検索してください。"})
    finally:
        connection.close()


def bounded_pipeline(query, emit):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=pipeline_worker, args=(query, sender), daemon=True)
    deadline = time.monotonic() + REQUEST_TIME_LIMIT
    worker.start()
    sender.close()
    try:
        while time.monotonic() < deadline:
            if receiver.poll(min(0.2, max(0, deadline - time.monotonic()))):
                try:
                    record = receiver.recv()
                except EOFError:
                    break
                emit(record)
                if record.get("kind") in {"result", "error"}:
                    return
            elif not worker.is_alive():
                break
        emit({"kind": "error", "message": "処理時間の上限に達しました。テーマを絞って再検索してください。"})
    finally:
        receiver.close()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=2)
        if worker.is_alive():
            worker.kill()
            worker.join(timeout=2)
        worker.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Queries and response bodies are deliberately not logged.
        pass

    def headers_for(self, status, mime, length=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if length is not None:
            self.send_header("Content-Length", str(length))
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.headers_for(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/health":
            self.reply(200, {"ok": True, "service": "timeline-generator"})
        elif path in ASSETS:
            file, mime = ASSETS[path]
            body = (ROOT / file).read_bytes()
            self.headers_for(200, mime, len(body))
            self.wfile.write(body)
        else:
            self.reply(404, {"error": "ページが見つかりません。"})

    def do_POST(self):
        if self.path != "/api/timeline":
            return self.reply(404, {"error": "ページが見つかりません。"})
        # Browser cross-origin and DNS-rebinding requests cannot trigger model calls.
        try:
            host = self.headers.get("Host", "")
            hostname = urlsplit("http://" + host).hostname
            allowed = {HOST, "127.0.0.1", "localhost", "ubuntu-server-app", "ubuntu-server-app.local"}
            origin = self.headers.get("Origin")
            if hostname not in allowed or (origin and origin != "http://" + host):
                return self.reply(403, {"error": "アプリと同じURLから検索してください。"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "JSON形式で検索してください。"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 2048:
                return self.reply(400, {"error": "検索条件が長すぎるか、空です。"})
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length))
            query = parse_query(payload.get("query") if isinstance(payload, dict) else None)
        except (ValueError, OSError, TimelineError) as exc:
            return self.reply(400, {"error": str(exc) if isinstance(exc, TimelineError) else "検索条件を読み取れませんでした。"})
        if not SLOT.acquire(blocking=False):
            return self.reply(429, {"error": "別の年表を作成中です。完了後に再検索してください。"})
        try:
            self.headers_for(200, "application/x-ndjson; charset=utf-8")
            def emit(data):
                self.wfile.write((json.dumps(data, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
            bounded_pipeline(query, emit)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            SLOT.release()


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"timeline-generator listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
