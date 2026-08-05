"""The question bank: exams, syllabus, questions, and the review loop.

Everything that reads or writes the database lives here so the FastAPI layer
stays about HTTP. Two rules are enforced at this level rather than in the UI:

- only `verified` questions are ever served (`due_questions`, `next_question`)
- answering always writes a `review` row, even when the card state update is a
  no-op, so the history stays complete
"""

from __future__ import annotations

import datetime as dt
import re

from . import db, srs
from .config import settings

STATUSES = ("draft", "verified", "held", "rejected")


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "exam"


# --- exams ---------------------------------------------------------------

def create_exam(name: str, slug: str = "") -> int:
    slug = slug or slugify(name)
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO exam (slug, name, created_at) VALUES (?, ?, ?)",
            (slug, name.strip(), _now()),
        )
    return int(cur.lastrowid)


def list_exams() -> list[dict]:
    rows = db.connection().execute(
        "SELECT id, slug, name, created_at FROM exam ORDER BY created_at"
    ).fetchall()
    return [dict(row) for row in rows]


def get_exam(exam_id: int) -> dict | None:
    row = db.connection().execute(
        "SELECT id, slug, name, created_at FROM exam WHERE id = ?", (exam_id,)
    ).fetchone()
    return dict(row) if row else None


def delete_exam(exam_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM exam WHERE id = ?", (exam_id,))


# --- syllabus ------------------------------------------------------------

def set_syllabus(exam_id: int, nodes: list[dict]) -> int:
    """Replace the syllabus for an exam.

    Questions keep their `node_path` string rather than a foreign key, so
    re-importing a syllabus never orphans or deletes existing questions; a
    renamed path simply stops matching and shows up as an unmapped branch.
    """
    with db.transaction() as conn:
        conn.execute("DELETE FROM syllabus_node WHERE exam_id = ?", (exam_id,))
        conn.executemany(
            "INSERT INTO syllabus_node (exam_id, path, title, weight, keywords)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (
                    exam_id,
                    str(node["path"]).strip(),
                    str(node["title"]).strip(),
                    float(node.get("weight", 1.0)),
                    str(node.get("keywords", "")).strip(),
                )
                for node in nodes
                if str(node.get("path", "")).strip() and str(node.get("title", "")).strip()
            ],
        )
    return len(nodes)


def list_syllabus(exam_id: int) -> list[dict]:
    rows = db.connection().execute(
        "SELECT path, title, weight, keywords FROM syllabus_node"
        " WHERE exam_id = ? ORDER BY path",
        (exam_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def parse_syllabus_outline(text: str) -> list[dict]:
    """Parse the indented outline the settings screen accepts.

    Format, one node per line (`|` separates the optional keyword hints):

        1 機械学習の基礎
          1.1 教師あり学習 | 回帰, 分類, SVM

    Indentation is cosmetic — the dotted number in the path carries the tree —
    so a copy-pasted syllabus survives inconsistent leading spaces.
    """
    nodes: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keywords = ""
        if "|" in line:
            line, keywords = (part.strip() for part in line.split("|", 1))
        match = re.match(r"^([0-9]+(?:\.[0-9]+)*)[.)]?\s+(.*)$", line)
        if not match:
            continue
        title = match.group(2).strip()
        if not title:
            continue
        nodes.append({
            "path": match.group(1),
            "title": title,
            "weight": 1.0,
            "keywords": keywords,
        })
    return nodes


# --- questions -----------------------------------------------------------

def add_question(
    exam_id: int,
    node_path: str,
    stem: str,
    choices: list[str],
    answer: int,
    explanation: str = "",
    evidence: str = "",
    source_refs: list[str] | None = None,
    status: str = "draft",
    origin: str = "manual",
    hold_reason: str = "",
) -> int:
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO question (exam_id, node_path, stem, choices, answer,"
            " explanation, evidence, source_refs, status, hold_reason, origin, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                exam_id, node_path.strip(), stem.strip(), db.dumps(choices), int(answer),
                explanation.strip(), evidence.strip(), db.dumps(source_refs or []),
                status, hold_reason, origin, _now(),
            ),
        )
    return int(cur.lastrowid)


def _question_row(row) -> dict:
    item = dict(row)
    item["choices"] = db.loads(item["choices"])
    item["source_refs"] = db.loads(item["source_refs"])
    return item


def get_question(question_id: int) -> dict | None:
    row = db.connection().execute(
        "SELECT * FROM question WHERE id = ?", (question_id,)
    ).fetchone()
    return _question_row(row) if row else None


def list_questions(
    exam_id: int,
    status: str = "",
    node_prefix: str = "",
    query: str = "",
    limit: int = 200,
) -> list[dict]:
    sql = "SELECT * FROM question WHERE exam_id = ?"
    params: list = [exam_id]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if node_prefix:
        sql += " AND (node_path = ? OR node_path LIKE ?)"
        params.extend([node_prefix, f"{node_prefix}.%"])
    if query:
        sql += " AND (stem LIKE ? OR explanation LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = db.connection().execute(sql, params).fetchall()
    return [_question_row(row) for row in rows]


def set_status(question_id: int, status: str, hold_reason: str = "") -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    with db.transaction() as conn:
        conn.execute(
            "UPDATE question SET status = ?, hold_reason = ? WHERE id = ?",
            (status, hold_reason, question_id),
        )


def delete_question(question_id: int) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM question WHERE id = ?", (question_id,))


def counts_by_status(exam_id: int) -> dict[str, int]:
    rows = db.connection().execute(
        "SELECT status, COUNT(*) AS n FROM question WHERE exam_id = ? GROUP BY status",
        (exam_id,),
    ).fetchall()
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] = row["n"]
    return counts


# --- the review loop -----------------------------------------------------

def next_question(exam_id: int, node_prefix: str = "") -> dict | None:
    """The next card to serve: overdue first, then never-seen.

    Only `verified` questions are eligible. A question with no card row has
    never been answered, so it is new; new cards come last so that a backlog of
    due reviews is cleared before the workload grows.
    """
    now = _now()
    params: list = [exam_id]
    node_clause = ""
    if node_prefix:
        node_clause = " AND (q.node_path = ? OR q.node_path LIKE ?)"
        params.extend([node_prefix, f"{node_prefix}.%"])

    due_sql = (
        "SELECT q.* FROM question q JOIN card c ON c.question_id = q.id"
        " WHERE q.exam_id = ? AND q.status = 'verified' AND c.due_at <= ?" + node_clause +
        " ORDER BY c.due_at LIMIT 1"
    )
    row = db.connection().execute(due_sql, [params[0], now, *params[1:]]).fetchone()
    if row:
        return _question_row(row)

    new_sql = (
        "SELECT q.* FROM question q LEFT JOIN card c ON c.question_id = q.id"
        " WHERE q.exam_id = ? AND q.status = 'verified' AND c.question_id IS NULL" + node_clause +
        " ORDER BY q.id LIMIT 1"
    )
    row = db.connection().execute(new_sql, params).fetchone()
    return _question_row(row) if row else None


def queue_counts(exam_id: int) -> dict[str, int]:
    conn = db.connection()
    now = _now()
    due = conn.execute(
        "SELECT COUNT(*) FROM question q JOIN card c ON c.question_id = q.id"
        " WHERE q.exam_id = ? AND q.status = 'verified' AND c.due_at <= ?",
        (exam_id, now),
    ).fetchone()[0]
    fresh = conn.execute(
        "SELECT COUNT(*) FROM question q LEFT JOIN card c ON c.question_id = q.id"
        " WHERE q.exam_id = ? AND q.status = 'verified' AND c.question_id IS NULL",
        (exam_id,),
    ).fetchone()[0]
    return {"due": due, "new": fresh}


def answer(question_id: int, chosen: int | None, elapsed_ms: int = 0, unsure: bool = False) -> dict:
    """Record an answer and reschedule the card.

    The review row is written even when the answer is blank (`chosen is None`),
    because "did not know" is information the scheduler and the weakness tree
    both need.
    """
    question = get_question(question_id)
    if question is None:
        raise LookupError(f"no such question: {question_id}")
    correct = chosen is not None and int(chosen) == int(question["answer"])
    grade = srs.grade_for(correct, elapsed_ms, unsure=unsure)

    row = db.connection().execute(
        "SELECT interval, ease, reps, lapses FROM card WHERE question_id = ?",
        (question_id,),
    ).fetchone()
    state = srs.CardState(**dict(row)) if row else srs.CardState()
    next_state, due_at = srs.schedule(state, grade)

    now = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO review (question_id, answered_at, chosen, correct, elapsed_ms, grade)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, now, chosen, int(correct), int(elapsed_ms), grade),
        )
        conn.execute(
            "INSERT INTO card (question_id, due_at, interval, ease, reps, lapses, last_seen_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(question_id) DO UPDATE SET"
            " due_at = excluded.due_at, interval = excluded.interval, ease = excluded.ease,"
            " reps = excluded.reps, lapses = excluded.lapses, last_seen_at = excluded.last_seen_at",
            (
                question_id, due_at.isoformat(timespec="seconds"), next_state.interval,
                next_state.ease, next_state.reps, next_state.lapses, now,
            ),
        )
    return {
        "correct": correct,
        "answer": question["answer"],
        "explanation": question["explanation"],
        "evidence": question["evidence"],
        "source_refs": question["source_refs"],
        "grade": grade,
        "due_at": due_at.isoformat(timespec="seconds"),
        "interval": next_state.interval,
    }


# --- weakness ------------------------------------------------------------

def node_stats(exam_id: int) -> list[dict]:
    """Accuracy per syllabus node, counting a branch's descendants into it.

    Only the most recent answer per question counts. Averaging over every
    attempt buries recent improvement under old mistakes, which is exactly
    backwards for deciding what to study next.
    """
    conn = db.connection()
    rows = conn.execute(
        "SELECT q.node_path AS path, r.correct AS correct FROM question q"
        " JOIN review r ON r.id = ("
        "   SELECT id FROM review WHERE question_id = q.id ORDER BY answered_at DESC, id DESC LIMIT 1"
        " ) WHERE q.exam_id = ?",
        (exam_id,),
    ).fetchall()
    totals = conn.execute(
        "SELECT node_path AS path, COUNT(*) AS n FROM question"
        " WHERE exam_id = ? AND status = 'verified' GROUP BY node_path",
        (exam_id,),
    ).fetchall()

    answered: dict[str, list[int]] = {}
    for row in rows:
        answered.setdefault(row["path"], []).append(row["correct"])
    available = {row["path"]: row["n"] for row in totals}

    stats = []
    for node in list_syllabus(exam_id):
        path = node["path"]
        prefix = f"{path}."
        seen: list[int] = []
        total = 0
        for other, marks in answered.items():
            if other == path or other.startswith(prefix):
                seen.extend(marks)
        for other, count in available.items():
            if other == path or other.startswith(prefix):
                total += count
        stats.append({
            **node,
            "questions": total,
            "answered": len(seen),
            "correct": sum(seen),
            "accuracy": (sum(seen) / len(seen)) if seen else None,
            "depth": path.count("."),
        })
    return stats


def recent_reviews(exam_id: int, limit: int = 50) -> list[dict]:
    rows = db.connection().execute(
        "SELECT r.answered_at, r.correct, r.grade, q.stem, q.node_path"
        " FROM review r JOIN question q ON q.id = r.question_id"
        " WHERE q.exam_id = ? ORDER BY r.answered_at DESC, r.id DESC LIMIT ?",
        (exam_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
