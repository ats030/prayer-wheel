"""Explicit, additive import of missing editorial courses into the learning bank.

The JSON snapshots remain the editorial originals. Existing exams are never
overwritten or synchronised; this is not called from public requests/startup.
"""

import datetime as dt
import hashlib
import json

from . import db, kouko, products

EXAMS = {"kouko": "考古検定 入門クラス", **products.EXAMS}
DISPLAY_NAMES = (*products.EXAMS.values(), EXAMS["kouko"])
PROVIDER = "material-snapshot"


def ordered_exams(exams: list[dict]) -> list[dict]:
    """Match the material catalog; keep additional exams in their existing order."""
    rank = {name: index for index, name in enumerate(DISPLAY_NAMES)}
    return sorted(exams, key=lambda exam: rank.get(exam["name"], len(rank)))


def prepare_missing(exams: list[dict]) -> list[dict]:
    names = {e["name"] for e in exams}
    slugs = {e["slug"] for e in exams}
    prepared = []
    for key, name in EXAMS.items():
        if name in names:
            continue
        slug = f"material-{key}"
        if slug in slugs:
            raise ValueError(f"教材用の識別子が別の試験に使われています: {slug}")
        module = kouko if key == "kouko" else products
        raw = (module.PRODUCT_DIR / f"{key}.json").read_bytes()
        product = module.parse_product(raw)
        digest = hashlib.sha256(raw).hexdigest()
        categories = list(dict.fromkeys(q["category"] for q in product["questions"]))
        nodes = {}
        questions = []
        for q in product["questions"]:
            path = q.get("node_path") or str(categories.index(q["category"]) + 1)
            nodes.setdefault(path, q["category"])
            source_keys = q.get("source_keys", [q["source"]])
            refs = [product["sources"][source]["url"] for source in source_keys]
            provenance = q.get("provenance", {})
            details = [*provenance.get("source_details", []), {
                "provider": PROVIDER,
                "scope": key,
                "snapshot_checked_at": product["checked_at"],
                "editorial_question_id": q["id"],
                "editorial_source_keys": source_keys,
                "original_provenance": provenance,
                "editorial_content_sha256": digest,
                # Importing does not constitute human review or a rights check.
                "human_review": "未校閲",
            }]
            questions.append({
                "path": path, "stem": q["stem"], "choices": q["choices"],
                "answer": q["answer"], "explanation": q["explanation"],
                # A source support summary is not a verbatim evidence quote.
                "evidence": provenance.get("evidence", ""),
                "refs": refs, "details": details,
            })
        prepared.append({"key": key, "name": name, "slug": slug,
                         "nodes": nodes, "questions": questions})
    return prepared


def import_missing() -> list[dict]:
    """Create all missing courses atomically; repeated calls add nothing."""
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    created = []
    with db.transaction() as conn:
        # Serialise the existence check with inserts, including concurrent imports.
        conn.execute("BEGIN IMMEDIATE")
        exams = [dict(row) for row in conn.execute("SELECT name,slug FROM exam")]
        for course in prepare_missing(exams):
            cursor = conn.execute("INSERT INTO exam (name,slug,created_at) VALUES (?,?,?)",
                                  (course["name"], course["slug"], now))
            exam_id = cursor.lastrowid
            conn.executemany("INSERT INTO syllabus_node (exam_id,path,title) VALUES (?,?,?)",
                             [(exam_id, path, title) for path, title in course["nodes"].items()])
            for q in course["questions"]:
                conn.execute(
                    "INSERT INTO question (exam_id,node_path,stem,choices,answer,explanation,"
                    "evidence,source_refs,source_details,status,origin,created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,'verified','editorial',?)",
                    (exam_id, q["path"], q["stem"], db.dumps(q["choices"]), q["answer"],
                     q["explanation"], q["evidence"], db.dumps(q["refs"]), db.dumps(q["details"]), now),
                )
            created.append({"key": course["key"], "exam_id": exam_id,
                            "name": course["name"], "questions": len(course["questions"])})
    return created


def import_info(exam_id: int) -> dict | None:
    row = db.connection().execute(
        "SELECT source_details FROM question WHERE exam_id=? AND origin='editorial' ORDER BY id LIMIT 1",
        (exam_id,),
    ).fetchone()
    if row:
        for record in json.loads(row["source_details"]):
            key = record.get("scope")
            if record.get("provider") == PROVIDER and key in EXAMS:
                return {"url": "/kouko" if key == "kouko" else f"/products/{key}",
                        "human_review": record["human_review"]}
    return None
