"""Curated study-resource ads, kept separate from question explanations."""
from __future__ import annotations
import datetime as dt
from urllib.parse import urlparse
from . import db

def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

def _valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

def upsert(exam_id: int, node_path: str, title: str, url: str, reason: str = "") -> dict:
    node_path, title, url, reason = node_path.strip(), title.strip(), url.strip(), reason.strip()
    if not node_path or not title:
        raise ValueError("シラバス項目と教材名を入力してください")
    if not _valid_url(url):
        raise ValueError("教材URLは http:// または https:// で入力してください")
    now = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO affiliate_resource (exam_id,node_path,title,url,reason,active,created_at,updated_at)"
            " VALUES (?,?,?,?,?,1,?,?) ON CONFLICT(exam_id,node_path) DO UPDATE SET"
            " title=excluded.title,url=excluded.url,reason=excluded.reason,active=1,updated_at=excluded.updated_at",
            (exam_id, node_path, title, url, reason, now, now),
        )
    return for_node(exam_id, node_path) or {}

def list_for_exam(exam_id: int) -> list[dict]:
    rows = db.connection().execute(
        "SELECT r.*, SUM(CASE WHEN e.event_type='impression' THEN 1 ELSE 0 END) impressions,"
        " SUM(CASE WHEN e.event_type='click' THEN 1 ELSE 0 END) clicks"
        " FROM affiliate_resource r LEFT JOIN affiliate_event e ON e.resource_id=r.id"
        " WHERE r.exam_id=? GROUP BY r.id ORDER BY r.node_path", (exam_id,)
    ).fetchall()
    return [dict(row) for row in rows]

def for_node(exam_id: int, node_path: str) -> dict | None:
    row = db.connection().execute(
        "SELECT id,exam_id,node_path,title,reason FROM affiliate_resource"
        " WHERE exam_id=? AND node_path=? AND active=1", (exam_id, node_path)
    ).fetchone()
    return dict(row) if row else None

def set_active(resource_id: int, active: bool) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE affiliate_resource SET active=?,updated_at=? WHERE id=?",
                     (int(active), _now(), resource_id))

def record(resource_id: int, question_id: int | None, event_type: str) -> None:
    if event_type not in {"impression", "click"}:
        raise ValueError("unknown affiliate event")
    with db.transaction() as conn:
        if not conn.execute("SELECT 1 FROM affiliate_resource WHERE id=? AND active=1",
                            (resource_id,)).fetchone():
            raise LookupError("教材が見つかりません")
        conn.execute("INSERT INTO affiliate_event (resource_id,question_id,event_type,occurred_at)"
                     " VALUES (?,?,?,?)", (resource_id, question_id, event_type, _now()))

def click_target(resource_id: int, question_id: int | None = None) -> str:
    row = db.connection().execute(
        "SELECT url FROM affiliate_resource WHERE id=? AND active=1", (resource_id,)
    ).fetchone()
    if not row:
        raise LookupError("教材が見つかりません")
    record(resource_id, question_id, "click")
    return str(row["url"])
