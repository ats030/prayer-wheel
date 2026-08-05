"""Persistent generation jobs.

Generation runs SearXNG, then one model call per passage, then a verification
call per candidate — minutes, not seconds. The browser must not be what keeps
that alive, so jobs live in the database and a worker thread drains them. The
same arrangement writing uses for regeneration, minus the parts this app has no
use for.

State lives in SQLite rather than a JSON sidecar because the rest of this app is
already there and a job is naturally a row.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading

from . import db, generate

logger = logging.getLogger(__name__)

_worker: threading.Thread | None = None
_wake = threading.Event()
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS job (
    id           INTEGER PRIMARY KEY,
    exam_id      INTEGER NOT NULL,
    node_path    TEXT NOT NULL,
    target       INTEGER NOT NULL DEFAULT 5,
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued|running|done|error
    status_text  TEXT NOT NULL DEFAULT '',
    summary      TEXT NOT NULL DEFAULT '{}',
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_status ON job (status);
"""


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def init() -> None:
    with db.transaction() as conn:
        conn.executescript(_SCHEMA)


def enqueue(exam_id: int, node_path: str, target: int = 5) -> dict:
    init()
    with db.transaction() as conn:
        # One queued/running job per node. Pressing the button twice should not
        # double-generate; it should join the run already happening.
        row = conn.execute(
            "SELECT id FROM job WHERE exam_id = ? AND node_path = ?"
            " AND status IN ('queued', 'running')",
            (exam_id, node_path),
        ).fetchone()
        if row:
            return get(row["id"])
        cur = conn.execute(
            "INSERT INTO job (exam_id, node_path, target, created_at) VALUES (?, ?, ?, ?)",
            (exam_id, node_path, int(target), _now()),
        )
        job_id = int(cur.lastrowid)
    start_worker()
    _wake.set()
    return get(job_id)


def get(job_id: int) -> dict | None:
    init()
    row = db.connection().execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["summary"] = json.loads(item["summary"])
    except ValueError:
        item["summary"] = {}
    return item


def list_for_exam(exam_id: int, limit: int = 20) -> list[dict]:
    init()
    rows = db.connection().execute(
        "SELECT id FROM job WHERE exam_id = ? ORDER BY id DESC LIMIT ?",
        (exam_id, limit),
    ).fetchall()
    return [get(row["id"]) for row in rows]


def active(exam_id: int) -> list[dict]:
    return [job for job in list_for_exam(exam_id) if job["status"] in ("queued", "running")]


def _set(job_id: int, **fields) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key} = ?" for key in fields)
    with db.transaction() as conn:
        conn.execute(f"UPDATE job SET {columns} WHERE id = ?", [*fields.values(), job_id])


def _claim() -> dict | None:
    """Atomically take the oldest queued job."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT id FROM job WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        # The WHERE status check makes the claim safe if another worker raced us.
        changed = conn.execute(
            "UPDATE job SET status = 'running', status_text = '開始しています…'"
            " WHERE id = ? AND status = 'queued'",
            (row["id"],),
        ).rowcount
    return get(row["id"]) if changed else None


def _run(job: dict) -> None:
    job_id = job["id"]
    try:
        summary = generate.generate_for_node(
            job["exam_id"], job["node_path"], target=job["target"],
            progress=lambda text: _set(job_id, status_text=text),
        )
        _set(
            job_id,
            status="done",
            status_text=(
                f"採用 {summary['verified']} / 要確認 {summary['held']} / 破棄 {summary['dropped']}"
            ),
            summary=json.dumps(summary, ensure_ascii=False),
            finished_at=_now(),
        )
    except Exception as exc:  # a failed job must not take the worker with it
        logger.exception("generation job %s failed", job_id)
        _set(job_id, status="error", error=str(exc), finished_at=_now())


def _loop() -> None:
    while True:
        job = _claim()
        if job is None:
            _wake.wait(timeout=30)
            _wake.clear()
            continue
        _run(job)


def start_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_loop, name="exam-trainer-jobs", daemon=True)
        _worker.start()


def recover_running() -> None:
    """Put jobs that were running at shutdown back in the queue.

    A restart in the middle of a run would otherwise leave a job that says
    "running" forever with nothing running it.
    """
    init()
    with db.transaction() as conn:
        conn.execute(
            "UPDATE job SET status = 'queued', status_text = '再起動により再実行します'"
            " WHERE status = 'running'"
        )
