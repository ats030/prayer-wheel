from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from app_hub import config

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RecordResult:
    id: str
    created: bool


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def stable_id(prefix: str, *parts: object) -> str:
    h = sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return f"{prefix}_{h.hexdigest()[:24]}"


def json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, default=str)


def file_uri(path: Path) -> str:
    return path.expanduser().resolve().as_uri()


def hash_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    target = Path(path).expanduser() if path else config.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def _has_fts5(con: sqlite3.Connection) -> bool:
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
        con.execute("DROP TABLE IF EXISTS _fts_probe")
    except sqlite3.Error:
        return False
    return True


def init_db(con: sqlite3.Connection | None = None) -> None:
    if con is None:
        with connect() as owned:
            init_db(owned)
        return

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            app TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            ended_at TEXT,
            model TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_app_started
            ON runs(app, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_runs_status
            ON runs(status);

        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            app TEXT NOT NULL,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            mime TEXT,
            title TEXT,
            excerpt TEXT,
            created_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            UNIQUE(uri, sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_artifacts_app_created
            ON artifacts(app, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_kind
            ON artifacts(kind);

        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            title TEXT,
            captured_at TEXT,
            raw_ref TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            recorded_at TEXT NOT NULL,
            UNIQUE(kind, uri)
        );

        CREATE TABLE IF NOT EXISTS artifact_sources (
            artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'source',
            PRIMARY KEY (artifact_id, source_id, role)
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            app TEXT NOT NULL,
            run_id TEXT REFERENCES runs(id) ON DELETE SET NULL,
            ts TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_events_ts
            ON events(ts DESC);
        CREATE INDEX IF NOT EXISTS idx_events_level
            ON events(level);
        """
    )
    con.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    if _has_fts5(con):
        con.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS artifacts_fts
            USING fts5(artifact_id UNINDEXED, title, excerpt, metadata)
            """
        )
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('fts5', '1')"
        )
    else:
        con.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('fts5', '0')"
        )
    con.commit()


def record_run(
    *,
    app: str,
    action: str,
    status: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    model: str | None = None,
    params: dict[str, Any] | None = None,
    error: str | None = None,
    run_id: str | None = None,
    con: sqlite3.Connection | None = None,
) -> str:
    if con is None:
        with connect() as owned:
            init_db(owned)
            return record_run(
                app=app,
                action=action,
                status=status,
                started_at=started_at,
                ended_at=ended_at,
                model=model,
                params=params,
                error=error,
                run_id=run_id,
                con=owned,
            )

    rid = run_id or uuid.uuid4().hex
    con.execute(
        """
        INSERT INTO runs(
            id, app, action, status, started_at, ended_at, model,
            params_json, error, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            app=excluded.app,
            action=excluded.action,
            status=excluded.status,
            started_at=excluded.started_at,
            ended_at=excluded.ended_at,
            model=excluded.model,
            params_json=excluded.params_json,
            error=excluded.error
        """,
        (
            rid,
            app,
            action,
            status,
            started_at,
            ended_at,
            model,
            json_dumps(params),
            error,
            now_utc(),
        ),
    )
    con.commit()
    return rid


def _sync_artifact_fts(
    con: sqlite3.Connection,
    artifact_id: str,
    title: str | None,
    excerpt: str | None,
    metadata_json: str,
) -> None:
    fts = con.execute(
        "SELECT value FROM meta WHERE key='fts5'"
    ).fetchone()
    if not fts or fts["value"] != "1":
        return
    con.execute("DELETE FROM artifacts_fts WHERE artifact_id = ?", (artifact_id,))
    con.execute(
        """
        INSERT INTO artifacts_fts(artifact_id, title, excerpt, metadata)
        VALUES (?, ?, ?, ?)
        """,
        (artifact_id, title or "", excerpt or "", metadata_json),
    )


def record_artifact(
    *,
    app: str,
    kind: str,
    uri: str,
    sha256_value: str,
    run_id: str | None = None,
    mime: str | None = None,
    title: str | None = None,
    excerpt: str | None = None,
    created_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    con: sqlite3.Connection | None = None,
) -> RecordResult:
    if con is None:
        with connect() as owned:
            init_db(owned)
            return record_artifact(
                app=app,
                kind=kind,
                uri=uri,
                sha256_value=sha256_value,
                run_id=run_id,
                mime=mime,
                title=title,
                excerpt=excerpt,
                created_at=created_at,
                metadata=metadata,
                artifact_id=artifact_id,
                con=owned,
            )

    existing = con.execute(
        "SELECT id FROM artifacts WHERE uri = ? AND sha256 = ?",
        (uri, sha256_value),
    ).fetchone()
    aid = existing["id"] if existing else artifact_id or uuid.uuid4().hex
    metadata_json = json_dumps(metadata)
    con.execute(
        """
        INSERT INTO artifacts(
            id, run_id, app, kind, uri, sha256, mime, title, excerpt,
            created_at, metadata_json, recorded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uri, sha256) DO UPDATE SET
            run_id=COALESCE(excluded.run_id, artifacts.run_id),
            app=excluded.app,
            kind=excluded.kind,
            mime=excluded.mime,
            title=excluded.title,
            excerpt=excluded.excerpt,
            created_at=excluded.created_at,
            metadata_json=excluded.metadata_json
        """,
        (
            aid,
            run_id,
            app,
            kind,
            uri,
            sha256_value,
            mime,
            title,
            excerpt,
            created_at,
            metadata_json,
            now_utc(),
        ),
    )
    _sync_artifact_fts(con, aid, title, excerpt, metadata_json)
    con.commit()
    return RecordResult(aid, existing is None)


def record_source(
    *,
    kind: str,
    uri: str,
    title: str | None = None,
    captured_at: str | None = None,
    raw_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
    source_id: str | None = None,
    con: sqlite3.Connection | None = None,
) -> RecordResult:
    if con is None:
        with connect() as owned:
            init_db(owned)
            return record_source(
                kind=kind,
                uri=uri,
                title=title,
                captured_at=captured_at,
                raw_ref=raw_ref,
                metadata=metadata,
                source_id=source_id,
                con=owned,
            )

    existing = con.execute(
        "SELECT id FROM sources WHERE kind = ? AND uri = ?", (kind, uri)
    ).fetchone()
    sid = existing["id"] if existing else source_id or uuid.uuid4().hex
    con.execute(
        """
        INSERT INTO sources(
            id, kind, uri, title, captured_at, raw_ref, metadata_json, recorded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(kind, uri) DO UPDATE SET
            title=COALESCE(excluded.title, sources.title),
            captured_at=COALESCE(excluded.captured_at, sources.captured_at),
            raw_ref=COALESCE(excluded.raw_ref, sources.raw_ref),
            metadata_json=excluded.metadata_json
        """,
        (
            sid,
            kind,
            uri,
            title,
            captured_at,
            raw_ref,
            json_dumps(metadata),
            now_utc(),
        ),
    )
    con.commit()
    return RecordResult(sid, existing is None)


def link_artifact_source(
    artifact_id: str,
    source_id: str,
    *,
    role: str = "source",
    con: sqlite3.Connection,
) -> None:
    con.execute(
        """
        INSERT OR IGNORE INTO artifact_sources(artifact_id, source_id, role)
        VALUES (?, ?, ?)
        """,
        (artifact_id, source_id, role),
    )
    con.commit()


def record_event(
    *,
    app: str,
    level: str,
    message: str,
    run_id: str | None = None,
    ts: str | None = None,
    context: dict[str, Any] | None = None,
    event_id: str | None = None,
    con: sqlite3.Connection | None = None,
) -> str:
    if con is None:
        with connect() as owned:
            init_db(owned)
            return record_event(
                app=app,
                level=level,
                message=message,
                run_id=run_id,
                ts=ts,
                context=context,
                event_id=event_id,
                con=owned,
            )
    eid = event_id or uuid.uuid4().hex
    con.execute(
        """
        INSERT OR REPLACE INTO events(
            id, app, run_id, ts, level, message, context_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (eid, app, run_id, ts or now_utc(), level, message, json_dumps(context)),
    )
    con.commit()
    return eid


def recent_artifacts(
    *,
    limit: int = 20,
    app: str | None = None,
    con: sqlite3.Connection,
) -> list[sqlite3.Row]:
    params: list[Any] = []
    where = ""
    if app:
        where = "WHERE app = ?"
        params.append(app)
    params.append(limit)
    return list(
        con.execute(
            f"""
            SELECT id, app, kind, title, uri, created_at, recorded_at
            FROM artifacts
            {where}
            ORDER BY COALESCE(created_at, recorded_at) DESC
            LIMIT ?
            """,
            params,
        )
    )


def _fts_query(query: str) -> str:
    terms = [term.strip().replace('"', '""') for term in query.split() if term.strip()]
    if not terms:
        return '""'
    return " ".join(f'"{term}"' for term in terms)


def find_artifacts(
    query: str,
    *,
    limit: int = 20,
    app: str | None = None,
    con: sqlite3.Connection,
) -> list[sqlite3.Row]:
    fts = con.execute("SELECT value FROM meta WHERE key='fts5'").fetchone()
    params: list[Any]
    if fts and fts["value"] == "1":
        try:
            params = [_fts_query(query)]
            app_filter = ""
            if app:
                app_filter = "AND a.app = ?"
                params.append(app)
            params.append(limit)
            rows = list(
                con.execute(
                    f"""
                    SELECT a.id, a.app, a.kind, a.title, a.excerpt, a.uri,
                           a.created_at, bm25(artifacts_fts) AS rank
                    FROM artifacts_fts
                    JOIN artifacts a ON a.id = artifacts_fts.artifact_id
                    WHERE artifacts_fts MATCH ?
                    {app_filter}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    params,
                )
            )
            if rows:
                return rows
        except sqlite3.Error:
            pass

    like = f"%{query}%"
    params = [like, like, like]
    app_filter = ""
    if app:
        app_filter = "AND app = ?"
        params.append(app)
    params.append(limit)
    return list(
        con.execute(
            f"""
            SELECT id, app, kind, title, excerpt, uri, created_at, 0 AS rank
            FROM artifacts
            WHERE (
                COALESCE(title, '') LIKE ?
                OR COALESCE(excerpt, '') LIKE ?
                OR COALESCE(metadata_json, '') LIKE ?
            )
            {app_filter}
            ORDER BY COALESCE(created_at, recorded_at) DESC
            LIMIT ?
            """,
            params,
        )
    )


def failure_rows(
    *,
    limit: int = 20,
    con: sqlite3.Connection,
) -> list[sqlite3.Row]:
    return list(
        con.execute(
            """
            SELECT 'event' AS type, app, ts, level, message, context_json AS detail
            FROM events
            WHERE lower(level) IN ('error', 'warning')
            UNION ALL
            SELECT 'run' AS type, app, COALESCE(ended_at, started_at, created_at) AS ts,
                   status AS level, action AS message, COALESCE(error, '') AS detail
            FROM runs
            WHERE lower(status) IN ('failed', 'error')
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        )
    )
