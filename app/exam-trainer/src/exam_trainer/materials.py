"""Collected source material for a syllabus node.

Material is stored in the database rather than only in ~/cache because a
question's evidence has to remain checkable later: the page it came from may
change or disappear, and "the URL 404s now" must not turn a verified question
into an unverifiable one.
"""

from __future__ import annotations

import datetime as dt
import logging

from . import db, web

logger = logging.getLogger(__name__)

# Material older than this is re-collected. Exam syllabi move slowly; the point
# is to catch a page that has been rewritten, not to chase daily edits.
STALE_DAYS = 90


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def list_for_node(exam_id: int, node_path: str) -> list[dict]:
    rows = db.connection().execute(
        "SELECT url, title, text, fetched_at FROM material"
        " WHERE exam_id = ? AND node_path = ? ORDER BY fetched_at DESC",
        (exam_id, node_path),
    ).fetchall()
    return [dict(row) for row in rows]


def save(exam_id: int, node_path: str, url: str, title: str, text: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO material (exam_id, node_path, url, title, text, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(exam_id, node_path, url) DO UPDATE SET"
            " title = excluded.title, text = excluded.text, fetched_at = excluded.fetched_at",
            (exam_id, node_path, url, title, text, _now()),
        )


def _fresh(rows: list[dict]) -> list[dict]:
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=STALE_DAYS)
    fresh = []
    for row in rows:
        try:
            fetched = dt.datetime.fromisoformat(row["fetched_at"])
        except ValueError:
            continue
        if fetched >= cutoff:
            fresh.append(row)
    return fresh


def search_query(exam_name: str, node: dict) -> str:
    """What to ask the search engine for this node.

    The exam name is included so a generic term ("汎化") lands on pages written
    for this exam's level rather than on a research paper.
    """
    parts = [exam_name, node["title"]]
    if node.get("keywords"):
        parts.append(node["keywords"].replace(",", " "))
    return " ".join(part for part in parts if part).strip()


def ensure(exam_id: int, node: dict, exam_name: str, limit: int = 4) -> list[dict]:
    """Return usable material for a node, collecting it first if needed."""
    existing = _fresh(list_for_node(exam_id, node["path"]))
    if existing:
        return existing
    if not web.available():
        logger.info("SEARXNG_API_URL not set; no material can be collected")
        return []
    for material in web.gather(search_query(exam_name, node), limit=limit):
        save(exam_id, node["path"], material.url, material.title, material.text)
    return list_for_node(exam_id, node["path"])
