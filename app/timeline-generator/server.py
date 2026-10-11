#!/usr/bin/env python3
"""Private HTTP application with a durable, single-worker generation queue."""
import json
import multiprocessing
import os
import re
import signal
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from timeline import TIME_LIMIT, TimelineError, build_timeline, parse_query, partial_result
from jobs import JobStore, QueueWorker
import quality_eval
from milestones import report as milestone_report

ROOT = Path(__file__).resolve().parent
HOST = os.environ.get("TIMELINE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TIMELINE_PORT", "8532"))
REQUEST_TIME_LIMIT = TIME_LIMIT
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"), "/changelog": ("changelog.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/tokens.css": ("tokens.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
ASSETS["/timelines"] = ("index.html", "text/html; charset=utf-8")
ASSETS["/quality"] = ("quality.html", "text/html; charset=utf-8")
ASSETS["/library"] = ("library.html", "text/html; charset=utf-8")
ASSETS["/local-library.js"] = ("local-library.js", "text/javascript; charset=utf-8")


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


def bounded_pipeline(query, emit, stopping=None):
    if stopping is not None and stopping.is_set():
        return
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=pipeline_worker, args=(query, sender), daemon=True)
    started = time.monotonic()
    deadline = started + REQUEST_TIME_LIMIT
    checkpoint = None
    interrupted = False
    worker.start()
    sender.close()
    try:
        while time.monotonic() < deadline:
            if stopping is not None and stopping.is_set():
                return
            try:
                ready = receiver.poll(min(0.2, max(0, deadline - time.monotonic())))
                record = receiver.recv() if ready else None
            except (EOFError, OSError):
                # Only transport failures fall back; database emit failures must propagate.
                interrupted = True
                break
            if ready:
                if record.get("kind") == "checkpoint":
                    if record.get("events"):
                        checkpoint = record
                    continue
                if record.get("kind") == "error" and checkpoint:
                    emit(partial_result(query, checkpoint, started, "processing_error"))
                    return
                emit(record)
                if record.get("kind") in {"result", "error"}:
                    return
            elif not worker.is_alive():
                interrupted = True
                break
        if checkpoint:
            emit(partial_result(query, checkpoint, started, "processing_error" if interrupted or time.monotonic() < deadline else "time_limit"))
        else:
            emit({"kind": "error", "message": "処理を完了できず、検証済みの出来事を保存できませんでした。再試行してください。"})
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

    def same_site(self):
        try:
            host = self.headers.get("Host", "")
            hostname = urlsplit("http://" + host).hostname
            allowed = {HOST, "127.0.0.1", "localhost", "ubuntu-server-app", "ubuntu-server-app.local"}
            origin = self.headers.get("Origin")
            return hostname in allowed and (not origin or origin == "http://" + host)
        except ValueError:
            return False

    def do_GET(self):
        # Persisted queries/results also require protection against DNS rebinding.
        if not self.same_site():
            return self.reply(403, {"error": "アプリと同じURLから閲覧してください。"})
        path = urlsplit(self.path).path
        if path == "/api/health":
            ok = self.server.worker.thread.is_alive()
            self.reply(200 if ok else 503, {"ok": ok, "service": "timeline-generator"})
        elif path == "/api/jobs":
            try:
                params = parse_qs(urlsplit(self.path).query)
                offset = int(params.get("offset", ["0"])[0])
                if not 0 <= offset <= 2**63 - 1:
                    raise ValueError
            except ValueError:
                return self.reply(400, {"error": "一覧の開始位置が不正です。"})
            self.reply(200, self.server.jobs.listing(offset=offset))
        elif path == "/api/quality":
            rows = []
            for item in self.server.jobs.listing(limit=50)["jobs"]:
                job = item["has_result"] and self.server.jobs.get(item["id"])
                if not job:
                    continue
                try:
                    report = quality_eval.job_quality(job)
                except (OSError, ValueError, KeyError):
                    return self.reply(500, {"error": "評価基準を読み込めませんでした。"})
                rows.append({"id": job["id"], "query": job["query"], "state": job["state"],
                             "updated_at": job["updated_at"], "theme": report["theme"], "axes": report["axes"]})
            self.reply(200, {"jobs": rows})
        elif re.fullmatch(r"/api/jobs/[1-9][0-9]{0,17}", path):
            job = self.server.jobs.get(int(path.rsplit("/", 1)[1]))
            if not job:
                return self.reply(404, {"error": "年表が見つかりません。"})
            if not job['legacy_period']:
                job['milestone_report'] = milestone_report(job['requested_milestones'], job.get('result') or {})
            try:
                job["quality"] = quality_eval.job_quality(job)
                gold = json.loads(quality_eval.GOLD_PATH.read_text(encoding='utf-8'))
                theme = quality_eval.find_theme(gold, job.get('result'), job['query'])
                suggestions = [
                    {'name': m['label'], 'year': m['years'][0] if m.get('years') and m['years'][0] == m['years'][1] else None,
                     'note': m.get('note', ''), 'url': (m.get('evidence') or [''])[0]}
                    for m in gold['themes'].get(theme, {}).get('milestones', [])]
                if not job['legacy_period']:
                    job['suggested_milestones'] = suggestions
            except (OSError, ValueError, KeyError):
                # A broken gold file must not hide the timeline itself.
                job["quality"] = None
            if job.get("result"):
                # The processing trace is for offline evaluation and can be tens of KB.
                job["result"].pop("trace", None)
            self.reply(200, job)
        elif re.fullmatch(r"/timelines/[1-9][0-9]{0,17}", path):
            if not self.server.jobs.get(int(path.rsplit("/", 1)[1])):
                return self.reply(404, {"error": "年表が見つかりません。"})
            body = (ROOT / "detail.html").read_bytes()
            self.headers_for(200, "text/html; charset=utf-8", len(body))
            self.wfile.write(body)
        elif path in ASSETS:
            file, mime = ASSETS[path]
            body = (ROOT / file).read_bytes()
            self.headers_for(200, mime, len(body))
            self.wfile.write(body)
        else:
            self.reply(404, {"error": "ページが見つかりません。"})

    def do_POST(self):
        action = re.fullmatch(r"/api/jobs/([1-9][0-9]{0,17})/(retry|regenerate|delete|cancel|milestones)", self.path)
        if self.path != "/api/jobs" and action is None:
            return self.reply(404, {"error": "ページが見つかりません。"})
        # Browser cross-origin and DNS-rebinding requests cannot trigger model calls.
        try:
            if not self.same_site():
                return self.reply(403, {"error": "アプリと同じURLから検索してください。"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.reply(415, {"error": "JSON形式で検索してください。"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= (65536 if action and action[2] == 'milestones' else 2048):
                return self.reply(400, {"error": "検索条件が長すぎるか、空です。"})
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError
            query = parse_query(payload.get("query")) if action is None else None
        except (ValueError, OSError, TimelineError) as exc:
            return self.reply(400, {"error": str(exc) if isinstance(exc, TimelineError) else "検索条件を読み取れませんでした。"})
        if action is None:
            job, created = self.server.jobs.submit(query)
            status = 201 if created else 200
        else:
            try:
                identifier = int(action[1])
                if action[2] == "delete":
                    job = self.server.jobs.delete(identifier)
                elif action[2] == "cancel":
                    job = self.server.jobs.cancel(identifier)
                elif action[2] == 'milestones':
                    job = self.server.jobs.save_milestones(identifier, payload.get('items'), payload.get('revision'))
                else:
                    job = self.server.jobs.requeue(identifier, action[2])
            except ValueError as exc:
                return self.reply(409, {"error": str(exc)})
            if job is None:
                return self.reply(404, {"error": "年表が見つかりません。"})
            status = 200
        job['milestone_report'] = milestone_report(job.get('requested_milestones', []), job.get('result') or {})
        if not action or action[2] != 'milestones':
            self.server.worker.wake.set()
        self.reply(status, job)


if __name__ == "__main__":
    jobs = JobStore(os.environ.get("TIMELINE_DB", str(ROOT / "data" / "timelines.sqlite3")))
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    # Idle browser keep-alive sockets must not delay SIGTERM/restart.
    server.daemon_threads = True
    server.jobs = jobs
    server.worker = QueueWorker(jobs, bounded_pipeline, on_failure=lambda: os._exit(1))
    server.worker.start()
    def shutdown(signum, frame):
        server.worker.stopping.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"timeline-generator listening on {HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.worker.stop()
        server.server_close()
        jobs.close()
