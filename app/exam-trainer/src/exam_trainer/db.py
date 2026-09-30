"""SQLite schema and connection handling.

Why SQLite rather than the Markdown-is-truth arrangement writing uses: the
review log grows a row per answer forever, and every screen is an aggregate
over it (accuracy per syllabus node, what is due now). Files would make both
the append and the aggregate awkward.

The schema is created on demand and migrated forward by `_MIGRATIONS`; there is
no separate migration tool to run.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

_local = threading.local()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exam (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Syllabus nodes form a tree by materialised path ("3/3.2"), which keeps the
-- "accuracy for this branch and everything under it" query a prefix match.
CREATE TABLE IF NOT EXISTS syllabus_node (
    id          INTEGER PRIMARY KEY,
    exam_id     INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    title       TEXT NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    keywords    TEXT NOT NULL DEFAULT '',
    UNIQUE (exam_id, path)
);

CREATE TABLE IF NOT EXISTS material (
    id          INTEGER PRIMARY KEY,
    exam_id     INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    node_path   TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    text        TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    UNIQUE (exam_id, node_path, url)
);

-- status: draft (generated, unchecked) / verified (passed the gate, may be
-- served) / held (the verifier disagreed; needs a human) / rejected.
-- Only `verified` is ever served, so a bad question fails closed.
CREATE TABLE IF NOT EXISTS question (
    id           INTEGER PRIMARY KEY,
    exam_id      INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
    node_path    TEXT NOT NULL,
    stem         TEXT NOT NULL,
    choices      TEXT NOT NULL,          -- JSON array of strings
    answer       INTEGER NOT NULL,       -- index into choices
    explanation  TEXT NOT NULL DEFAULT '',
    evidence     TEXT NOT NULL DEFAULT '',
    source_refs  TEXT NOT NULL DEFAULT '[]',  -- JSON array of URLs
    status       TEXT NOT NULL DEFAULT 'draft',
    hold_reason  TEXT NOT NULL DEFAULT '',
    origin       TEXT NOT NULL DEFAULT 'manual',  -- manual | generated
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_question_exam_status
    ON question (exam_id, status);
CREATE INDEX IF NOT EXISTS idx_question_node ON question (exam_id, node_path);

-- One row per answer, ever. Deliberately append-only: the SM-2 state in `card`
-- is derived from it, so a scheduler change can be replayed rather than lost.
CREATE TABLE IF NOT EXISTS review (
    id           INTEGER PRIMARY KEY,
    question_id  INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
    answered_at  TEXT NOT NULL,
    chosen       INTEGER,
    correct      INTEGER NOT NULL,
    elapsed_ms   INTEGER NOT NULL DEFAULT 0,
    grade        INTEGER NOT NULL       -- 0-5, SM-2 quality
);
CREATE INDEX IF NOT EXISTS idx_review_question ON review (question_id);

CREATE TABLE IF NOT EXISTS card (
    question_id  INTEGER PRIMARY KEY REFERENCES question(id) ON DELETE CASCADE,
    due_at       TEXT NOT NULL,
    interval     INTEGER NOT NULL DEFAULT 0,   -- days
    ease         REAL NOT NULL DEFAULT 2.5,
    reps         INTEGER NOT NULL DEFAULT 0,
    lapses       INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_card_due ON card (due_at);
"""

# Each entry runs once, in order, guarded by PRAGMA user_version. Append only.
_MIGRATIONS: list[str] = [
    """
    CREATE TABLE affiliate_resource (
        id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL REFERENCES exam(id) ON DELETE CASCADE,
        node_path TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE (exam_id, node_path)
    );
    CREATE INDEX idx_affiliate_resource_lookup ON affiliate_resource (exam_id, node_path, active);
    CREATE TABLE affiliate_event (
        id INTEGER PRIMARY KEY, resource_id INTEGER NOT NULL REFERENCES affiliate_resource(id) ON DELETE CASCADE,
        question_id INTEGER REFERENCES question(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL CHECK (event_type IN ('impression', 'click')), occurred_at TEXT NOT NULL
    );
    CREATE INDEX idx_affiliate_event_resource ON affiliate_event (resource_id, event_type, occurred_at);
    """,
    """
    ALTER TABLE material ADD COLUMN search_scope TEXT NOT NULL DEFAULT 'legacy';
    ALTER TABLE material ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE question ADD COLUMN source_details TEXT NOT NULL DEFAULT '[]';
    """,
]


def _connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    # WAL keeps a long-running read (the weakness tree) from blocking the write
    # that records an answer.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def connection() -> sqlite3.Connection:
    """One connection per thread; sqlite3 objects are not shareable across them."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _init(conn)
        _local.conn = conn
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, statement in enumerate(_MIGRATIONS[version:], start=version):
        conn.executescript(statement)
        conn.execute(f"PRAGMA user_version={index + 1}")
    conn.commit()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def reset_for_tests(path: Path) -> None:
    """Point the process at a throwaway database (tests only)."""
    close()
    settings.data_dir = path
    _local.conn = None


def close() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def loads(value: str) -> list:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def dumps(value: list) -> str:
    return json.dumps(value, ensure_ascii=False)
