"""Collected source material for a syllabus node.

Material is stored in the database rather than only in ~/cache because a
question's evidence has to remain checkable later: the page it came from may
change or disappear, and "the URL 404s now" must not turn a verified question
into an unverifiable one.
"""

from __future__ import annotations

import datetime as dt
import logging
import json

from . import db, web

logger = logging.getLogger(__name__)

# Material older than this is re-collected. Exam syllabi move slowly; the point
# is to catch a page that has been rewritten, not to chase daily edits.
STALE_DAYS = 90


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def list_for_node(exam_id: int, node_path: str) -> list[dict]:
    rows = db.connection().execute(
        "SELECT url, title, text, fetched_at, search_scope, provenance FROM material"
        " WHERE exam_id = ? AND node_path = ? ORDER BY fetched_at DESC",
        (exam_id, node_path),
    ).fetchall()
    return [{**dict(row), "provenance": json.loads(row["provenance"])} for row in rows]


def save(exam_id: int, node_path: str, url: str, title: str, text: str,
         provenance: dict | None = None) -> None:
    provenance = provenance or {}
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO material (exam_id, node_path, url, title, text, fetched_at, search_scope, provenance)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(exam_id, node_path, url) DO UPDATE SET"
            " title = excluded.title, text = excluded.text, fetched_at = excluded.fetched_at,"
            " search_scope = excluded.search_scope, provenance = excluded.provenance",
            (exam_id, node_path, url, title, text, _now(), provenance.get("scope", "manual"), json.dumps(provenance, ensure_ascii=False)),
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


def add_from_urls(exam_id: int, node_path: str, urls: list[str]) -> dict:
    """Fetch the given pages and keep them as material for one node.

    The only other way material arrives is a SearXNG search, which stops dead
    when the upstream engines throttle. Naming the pages directly also lets an
    official syllabus page be the source instead of whatever a search surfaced.
    """
    added, failed = [], []
    for raw in urls:
        url = raw.strip()
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            failed.append({"url": url, "reason": "http(s) の URL ではありません"})
            continue
        material = web.extract_url(url)
        if material is None:
            # extract_url already rejects garbled text, so this covers both a
            # failed fetch and a page with no extractable body.
            failed.append({"url": url, "reason": "本文を取り出せませんでした"})
            continue
        save(exam_id, node_path, material.url, material.title, material.text,
             {"scope": "manual", "fetched_url": material.url})
        added.append({"url": material.url, "title": material.title, "chars": len(material.text)})
    return {"added": added, "failed": failed}


def counts_by_node(exam_id: int) -> dict[str, int]:
    rows = db.connection().execute(
        "SELECT node_path, COUNT(*) AS n FROM material WHERE exam_id = ? GROUP BY node_path",
        (exam_id,),
    ).fetchall()
    return {row["node_path"]: row["n"] for row in rows}


def ensure(exam_id: int, node: dict, exam_name: str, limit: int = 4) -> list[dict]:
    """Return usable material for a node, collecting it first if needed."""
    existing = _fresh(list_for_node(exam_id, node["path"]))
    if web.settings.web_search_url:
        scope = web.current_scope()
        if scope == "sites":
            sources = web.reviewed_sources()
            kept = []
            for row in existing:
                source = next((s for s in sources if web.matches_source(row["url"], s)
                               and ((row["search_scope"] == "manual"
                                     and row["provenance"].get("fetched_url") == row["url"]) or
                                    (row["search_scope"] == "sites"
                                     and row["provenance"].get("provider") == s["id"]
                                     and row["provenance"].get("terms") == s["terms"]))), None)
                if source:
                    row["provenance"] = {"scope": "sites", "provider": source["id"],
                                         "terms": source["terms"], "url_prefixes": source["url_prefixes"]}
                    kept.append(row)
            existing = kept
        else:
            existing = [row for row in existing if row["search_scope"] in {scope, "manual"}]
    if existing:
        return existing
    if not web.available():
        logger.info("SEARXNG_API_URL not set; no material can be collected")
        return []
    # Site indexes should receive the topic, not an unrelated examination name.
    query = search_query("" if web.current_scope() == "sites" else exam_name, node)
    collected = web.gather(query, limit=limit)
    for material in collected:
        save(exam_id, node["path"], material.url, material.title, material.text, material.provenance)
    urls = {material.url for material in collected}
    return [row for row in list_for_node(exam_id, node["path"]) if row["url"] in urls]
