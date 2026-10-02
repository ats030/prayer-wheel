"""Durable FIFO and result store. One service process owns the worker."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from timeline import PERIOD_INPUT_ERROR, Query, TimelineError, parse_query

LEGACY_PERIOD_ERROR = "期間限定の年表は閲覧専用です。年代条件を外して新しく登録してください。"


def query_info(cache_key):
    """Derive archive status from the persisted request, not generated prose."""
    topic, start, end = json.loads(cache_key)
    return {"topic": topic, "period": Query("", topic, start, end).period,
            "legacy_period": start is not None or end is not None}


def can_delete(job):
    if job["state"] in {"queued", "running"} or job["legacy_period"]:
        return True
    count = job.get("event_count")
    if "result" in job:
        count = len(job["result"].get("events", [])) if job["result"] is not None else 0
    return not job["has_result"] or count == 0


class JobCancellation:
    def __init__(self, store, identifier, stopping):
        self.store, self.identifier, self.stopping = store, identifier, stopping

    def is_set(self):
        if self.stopping.is_set():
            return True
        with self.store.connect() as db:
            return db.execute("SELECT 1 FROM jobs WHERE id=?", (self.identifier,)).fetchone() is None

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            self.stopping.wait(0.1 if remaining is None else min(0.1, remaining))
        return True


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
        item.update(query_info(item.pop("cache_key")))
        result = item.pop("result")
        item["has_result"] = result is not None
        if detail:
            item["result"] = json.loads(result) if result is not None else None
        item["can_delete"] = can_delete(item)
        return item

    @staticmethod
    def next_order(db):
        db.execute("UPDATE counter SET value=value+1 WHERE id=1")
        return db.execute("SELECT value FROM counter WHERE id=1").fetchone()[0]

    def submit(self, query):
        if query.start is not None or query.end is not None:
            raise TimelineError(PERIOD_INPUT_ERROR)
        query = parse_query(query.original)
        key = json.dumps([query.topic, query.start, query.end], ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE cache_key=?", (key,)).fetchone()
            created = row is None
            if created:
                timestamp = now()
                # The durable counter never shrinks when rows are removed.
                order = self.next_order(db)
                cursor = db.execute("INSERT INTO jobs (id,cache_key,query,state,queue_order,created_at,updated_at,message) VALUES (?,?,?,'queued',?,?,?,'登録順に生成します。')", (order, key, query.original, order, timestamp, timestamp))
                row = db.execute("SELECT * FROM jobs WHERE id=?", (cursor.lastrowid,)).fetchone()
            return self.decode(row), created

    def get(self, identifier):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def listing(self, limit=50, offset=0):
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            rows = db.execute("""SELECT id, cache_key, query, state, queue_order, created_at, updated_at,
                started_at, stage, message, error, generated_at,
                result IS NOT NULL AS has_result, json_array_length(result, '$.events') AS event_count,
                json_extract(result, '$.stop_reason') AS stop_reason
                FROM jobs ORDER BY id DESC LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
            jobs = []
            for row in rows:
                item = dict(row)
                item.update(query_info(item.pop("cache_key")))
                item["has_result"] = bool(item["has_result"])
                item["can_delete"] = can_delete(item)
                jobs.append(item)
            return {"jobs": jobs, "total": total, "offset": offset, "limit": limit}

    def delete(self, identifier):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            job = self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())
            if job is None:
                return None
            if not job["can_delete"]:
                raise ValueError("収録済みの年表は削除できません。")
            db.execute("DELETE FROM jobs WHERE id=?", (identifier,))
            return {"id": identifier, "deleted": True}

    def requeue(self, identifier, action):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            if row is None:
                return None
            if query_info(row["cache_key"])["legacy_period"]:
                raise ValueError(LEGACY_PERIOD_ERROR)
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
            if job["legacy_period"]:
                self.store.record(job["id"], {"kind": "error", "message": LEGACY_PERIOD_ERROR})
                continue
            try:
                cancelled = JobCancellation(self.store, job["id"], self.stopping)
                if cancelled.is_set():
                    continue
                self.pipeline(parse_query(job["query"]), lambda record: self.store.record(job["id"], record), cancelled)
                current = self.store.get(job["id"])
                if not self.stopping.is_set() and current is not None and current["state"] == "running":
                    self.store.record(job["id"], {"kind": "error", "message": "生成結果を受け取れませんでした。再試行してください。"})
            except Exception:
                self.store.record(job["id"], {"kind": "error", "message": "生成を完了できませんでした。再試行してください。"})
