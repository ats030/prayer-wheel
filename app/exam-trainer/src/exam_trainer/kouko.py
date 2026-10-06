"""One editorial product, kept separate from the live learning bank.

Only the ten sample questions are exposed over HTTP. Public access requires a
human review of the exact content digest; editing the manuscript revokes it.
"""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

PRODUCT_DIR = Path(__file__).parent / "products"


def load_product() -> dict:
    product = json.loads((PRODUCT_DIR / "kouko.json").read_text())
    questions = product["questions"]
    ids = [q["id"] for q in questions]
    if len(questions) != 50 or len(set(ids)) != 50:
        raise ValueError("教材は重複のない50問が必要です")
    if len(product["free_ids"]) != 10 or len(set(product["free_ids"])) != 10:
        raise ValueError("無料体験は重複のない10問が必要です")
    if not set(product["free_ids"]) <= set(ids):
        raise ValueError("無料体験の問題IDが教材にありません")
    for q in questions:
        if (len(q["choices"]) != 4 or len(set(q["choices"])) != 4
                or not 0 <= q["answer"] < 4 or not q["explanation"].strip()
                or q["source"] not in product["sources"]):
            raise ValueError(f"問題{q['id']}の形式または出典が不正です")
    return product


def content_digest() -> str:
    return hashlib.sha256((PRODUCT_DIR / "kouko.json").read_bytes()).hexdigest()


def release_state() -> dict:
    release = json.loads((PRODUCT_DIR / "kouko-release.json").read_text())
    reviewed = (
        release.get("reviewed_sha256") == content_digest()
        and bool(release.get("reviewer")) and bool(release.get("reviewed_at"))
        and release.get("source_terms_checked") is True
    )
    url = release.get("booth_url", "")
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    valid_url = (
        parsed.scheme == "https" and (host == "booth.pm" or host.endswith(".booth.pm"))
        and parsed.netloc == host and re.fullmatch(r"/(?:ja/)?items/\d+", parsed.path)
        and not parsed.query and not parsed.fragment
    )
    return {"reviewed": reviewed, "booth_url": url if reviewed and valid_url else ""}


def sample_questions(product: dict) -> list[dict]:
    by_id = {q["id"]: q for q in product["questions"]}
    return [by_id[i] for i in product["free_ids"]]


def trial_payload(product: dict) -> list[dict]:
    return [{key: q[key] for key in ("id", "category", "stem", "choices")}
            for q in sample_questions(product)]


def check_answer(question_id: int, chosen: int) -> dict | None:
    product = load_product()
    q = next((q for q in sample_questions(product) if q["id"] == question_id), None)
    if q is None:
        return None
    source = product["sources"][q["source"]]
    return {"correct": chosen == q["answer"], "answer": q["answer"],
            "explanation": q["explanation"],
            "source": {"title": source["title"], "url": source["url"]}}
