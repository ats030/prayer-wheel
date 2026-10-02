"""Durable FIFO and result store. One service process owns the worker."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading

from timeline import parse_query


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = open(str(self.path) + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.connect() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, cache_key TEXT NOT NULL UNIQUE,
                    query TEXT NOT NULL, state TEXT NOT NULL,
                    queue_order INTEGER NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, started_at TEXT,
                    stage TEXT, message TEXT, error TEXT, result TEXT,
                    generated_at TEXT)""")
                db.execute("CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
                db.execute("INSERT OR IGNORE INTO counter VALUES (1, 0)")
                db.execute("CREATE INDEX IF NOT EXISTS fifo ON jobs(state, queue_order)")
                # A terminated worker restarts its interrupted item before later items.
                db.execute("UPDATE jobs SET state='queued', started_at=NULL, stage=NULL, message='再起動後の生成を待っています。', updated_at=? WHERE state='running'", (now(),))
            os.chmod(self.path, 0o600)
            os.chmod(str(self.path) + ".lock", 0o600)
        except BaseException:
            self.lock.close()
            raise

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        self.lock.close()

    @staticmethod
    def decode(row, detail=True):
        if row is None:
            return None
        item = dict(row)
        item.pop("cache_key", None)
        result = item.pop("result")
        item["has_result"] = result is not None
        if detail:
            item["result"] = json.loads(result) if result is not None else None
        return item

    @staticmethod
    def next_order(db):
        db.execute("UPDATE counter SET value=value+1 WHERE id=1")
        return db.execute("SELECT value FROM counter WHERE id=1").fetchone()[0]

    def submit(self, query):
        key = json.dumps([query.topic, query.start, query.end], ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE cache_key=?", (key,)).fetchone()
            created = row is None
            if created:
                timestamp = now()
                cursor = db.execute("INSERT INTO jobs (cache_key,query,state,queue_order,created_at,updated_at,message) VALUES (?,?,'queued',?,?,?,'登録順に生成します。')", (key, query.original, self.next_order(db), timestamp, timestamp))
                row = db.execute("SELECT * FROM jobs WHERE id=?", (cursor.lastrowid,)).fetchone()
            return self.decode(row), created

    def get(self, identifier):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def listing(self, limit=50, offset=0):
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            rows = db.execute("""SELECT id, query, state, queue_order, created_at, updated_at,
                started_at, stage, message, error, generated_at,
                result IS NOT NULL AS has_result, json_array_length(result, '$.events') AS event_count,
                json_extract(result, '$.stop_reason') AS stop_reason
                FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
            return {"jobs": [dict(row) | {"has_result": bool(row["has_result"])} for row in rows],
                    "total": total, "offset": offset, "limit": limit}

    def requeue(self, identifier, action):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            if row is None:
                return None
            if row["state"] in {"queued", "running"}:
                return self.decode(row)
            if action == "retry" and row["state"] != "failed":
                raise ValueError("失敗した処理だけ再試行できます。")
            if action == "regenerate" and row["result"] is None:
                raise ValueError("生成済みの年表だけ再生成できます。")
            db.execute("UPDATE jobs SET state='queued', queue_order=?, updated_at=?, started_at=NULL, stage=NULL, message='登録順に生成します。', error=NULL WHERE id=?", (self.next_order(db), now(), identifier))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY queue_order LIMIT 1").fetchone()
            if row is None:
                return None
            timestamp = now()
            db.execute("UPDATE jobs SET state='running', started_at=?, updated_at=?, message='生成を始めています。' WHERE id=?", (timestamp, timestamp, row["id"]))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def record(self, identifier, record):
        timestamp = now()
        with self.connect() as db:
            kind = record.get("kind")
            if kind == "result":
                message = {'time_limit': '時間上限により終了しました。検証済みの結果を保存しました。',
                           'processing_error': '途中で処理を終了しました。検証済みの結果を保存しました。'}.get(record.get('stop_reason'), '生成が完了しました。')
                db.execute("UPDATE jobs SET state='complete', result=?, generated_at=?, updated_at=?, error=NULL, message=? WHERE id=? AND state='running'", (json.dumps(record, ensure_ascii=False), timestamp, timestamp, message, identifier))
            elif kind == "error":
                db.execute("UPDATE jobs SET state='failed', error=?, updated_at=?, message='生成に失敗しました。' WHERE id=? AND state='running'", (record["message"], timestamp, identifier))
            elif kind == "progress":
                db.execute("UPDATE jobs SET stage=?, message=?, updated_at=? WHERE id=? AND state='running'", (record.get("stage"), record.get("message"), timestamp, identifier))


class QueueWorker:
    def __init__(self, store, pipeline, on_failure=None):
        self.store, self.pipeline = store, pipeline
        self.on_failure = on_failure
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.run, name="timeline-queue", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=6)

    def run(self):
        try:
            self.run_queue()
        except Exception:
            # A storage failure must not leave a healthy-looking service with no worker.
            if self.on_failure:
                self.on_failure()
            raise

    def run_queue(self):
        while not self.stopping.is_set():
            job = self.store.claim()
            if job is None:
                self.wake.wait(1)
                self.wake.clear()
                continue
            try:
                self.pipeline(parse_query(job["query"]), lambda record: self.store.record(job["id"], record), self.stopping)
                if not self.stopping.is_set() and self.store.get(job["id"])["state"] == "running":
                    self.store.record(job["id"], {"kind": "error", "message": "生成結果を受け取れませんでした。再試行してください。"})
            except Exception:
                self.store.record(job["id"], {"kind": "error", "message": "生成を完了できませんでした。再試行してください。"})
