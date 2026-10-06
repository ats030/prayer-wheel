"""One editorial product, kept separate from the live learning bank.

The trial serves ten questions. App visitors may read the complete editorial
artifacts; human review of the exact content digest controls sale readiness.
"""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

PRODUCT_DIR = Path(__file__).parent / "products"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "docs" / "kouko"


def artifacts() -> list[dict]:
    return artifact_list(ARTIFACT_DIR, content_digest(), 50, "kouko", release_state()["reviewed"])


def artifact_list(directory: Path, digest: str, count: int, prefix: str, reviewed: bool = False) -> list[dict]:
    """A fixed list of resources; never turn a caller's path into a filename."""
    specs = [
        ("review-pdf", f"{count}問の校閲用PDF", "問題、解答、全問解説と参考資料を収録。", f"{prefix}-review.pdf"),
        ("sample-pdf", "10問の見本PDF", "無料体験と同じ10問を収録。", f"{prefix}-sample.pdf"),
        ("manuscript", "問題と解説の原稿", f"全{count}問の問題、解説と出典をテキストで確認。", "manuscript.md"),
        ("sales-copy", "販売説明とSNSの原稿", "BOOTHの商品説明と一問解説の投稿案。", "sales-copy.md"),
        ("review-sheet", "校閲記録のCSV", "各問の確認結果や修正点を記入するシート。", f"review-{digest[:12]}.csv"),
        ("claim-audit", "根拠確認の記録", "問題の根拠と、校閲で確認する点。", "claim-audit.md"),
        ("release-guide", "校閲から販売までの手順", "校閲記録、PDFの更新、出品までの進め方。", "release-guide.md"),
    ]
    manifest = directory / "artifact-state.json"
    try:
        records = json.loads(manifest.read_text())
    except (OSError, ValueError):
        records = {}
    if not isinstance(records, dict):
        records = {}
    assets = []
    for key, title, description, filename in specs:
        path = directory / filename
        available = path.is_file()
        record = records.get(key, {})
        if not isinstance(record, dict):
            record = {}
        current = (available and record.get("content_sha256") == digest
                   and record.get("file_sha256") == hashlib.sha256(path.read_bytes()).hexdigest()
                   and (not record.get("reviewed_pdf") or reviewed))
        assets.append({"id": key, "title": title, "description": description, "path": path,
                       "media_type": "application/pdf" if filename.endswith(".pdf") else "text/plain; charset=utf-8",
                       "format": "PDF" if filename.endswith(".pdf") else "CSV" if filename.endswith(".csv") else "テキスト",
                       "available": available, "current": current})
    return assets


def record_artifacts(directory: Path, digest: str, count: int, prefix: str,
                     reviewed: bool, preserve: set[str] | None = None) -> None:
    """Record a completed build; preserved human copy stays on its own revision."""
    path = directory / "artifact-state.json"
    records = json.loads(path.read_text()) if path.exists() else {}
    for asset in artifact_list(directory, digest, count, prefix, reviewed):
        if not asset["available"] or asset["id"] in (preserve or set()):
            continue
        records[asset["id"]] = {"content_sha256": digest,
                                "file_sha256": hashlib.sha256(asset["path"].read_bytes()).hexdigest(),
                                "reviewed_pdf": reviewed if asset["format"] == "PDF" else False}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(records, indent=2) + "\n")
    temp.replace(path)


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
    return release_state_for(PRODUCT_DIR / "kouko-release.json", content_digest())


def release_state_for(path: Path, digest: str) -> dict:
    release = json.loads(path.read_text())
    reviewed = (
        release.get("reviewed_sha256") == digest
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
