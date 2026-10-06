"""Fixed editorial snapshots; never read or mutate the live learning bank."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import kouko

PRODUCT_DIR = Path(__file__).parent / "products"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "docs"
# These IDs, not user input or an exam's slug, select files on disk.
EXAMS = {
    "g": "G検定",
    "nihonshu": "日本酒検定",
    "rekishi-3": "歴史能力検定3級 日本史",
    "sekai-isan-3": "世界遺産検定3級",
    "jinja-3": "神社検定 参級",
    "shiro-3": "日本城郭検定3級",
}


def require_product(product_id: str) -> None:
    if product_id not in EXAMS:
        raise KeyError(product_id)


def load_product(product_id: str) -> dict:
    require_product(product_id)
    return parse_product((PRODUCT_DIR / f"{product_id}.json").read_bytes())


def parse_product(raw: bytes) -> dict:
    product = json.loads(raw)
    questions = product["questions"]
    ids = [q["id"] for q in questions]
    free_ids = product["free_ids"]
    if not 10 <= len(ids) <= 50 or len(set(ids)) != len(ids):
        raise ValueError("教材は重複のない10〜50問が必要です")
    if len(free_ids) != 10 or len(set(free_ids)) != 10 or not set(free_ids) <= set(ids):
        raise ValueError("無料体験は教材内の重複のない10問が必要です")
    for source in product["sources"].values():
        url = urlsplit(source["url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            raise ValueError("出典にはHTTP/HTTPSのURLが必要です")
    for q in questions:
        keys = q.get("source_keys", [q["source"]])
        if (len(q["choices"]) != 4 or len(set(q["choices"])) != 4
                or not 0 <= q["answer"] < 4 or not q["explanation"].strip()
                or not keys or q["source"] not in keys
                or any(key not in product["sources"] for key in keys)):
            raise ValueError(f"問題{q['id']}の形式または出典が不正です")
    return product


def content_digest(product_id: str) -> str:
    require_product(product_id)
    return hashlib.sha256((PRODUCT_DIR / f"{product_id}.json").read_bytes()).hexdigest()


def release_state(product_id: str) -> dict:
    require_product(product_id)
    return kouko.release_state_for(PRODUCT_DIR / f"{product_id}-release.json", content_digest(product_id))


def artifacts(product_id: str) -> list[dict]:
    product = load_product(product_id)
    return kouko.artifact_list(ARTIFACT_DIR / product_id, content_digest(product_id),
                               len(product["questions"]), product_id, release_state(product_id)["reviewed"])


def check_answer(product_id: str, question_id: int, chosen: int) -> dict | None:
    product = load_product(product_id)
    q = next((q for q in kouko.sample_questions(product) if q["id"] == question_id), None)
    if q is None:
        return None
    source = product["sources"][q["source"]]
    return {"correct": chosen == q["answer"], "answer": q["answer"],
            "explanation": q["explanation"],
            "source": {"title": source["title"], "url": source["url"]}}
