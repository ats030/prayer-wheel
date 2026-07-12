from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app_hub.db import (
    connect,
    file_uri,
    hash_file,
    init_db,
    link_artifact_source,
    now_utc,
    record_artifact,
    record_run,
    record_source,
    stable_id,
)

IMAGE_GALLERY = Path.home() / "pCloudDrive" / "My Picture" / "image-generator"
WRITING_DIR = Path.home() / "pCloudDrive" / "Obsidian" / "writing"
ZENN_ARTICLES_DIR = Path.home() / "pCloudDrive" / "Zenn" / "zenn-docs" / "articles"
URL_RE = re.compile(r"https?://[^\s<>)\"']+")
MAX_TEXT_BYTES = 2_000_000
FIND_TIMEOUT_SECONDS = 60


@dataclass
class BackfillStats:
    scanned: int = 0
    artifacts_created: int = 0
    artifacts_seen: int = 0
    sources_created: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "artifacts_created": self.artifacts_created,
            "artifacts_seen": self.artifacts_seen,
            "sources_created": self.sources_created,
            "errors": self.errors,
        }


def parse_loose_datetime(value: object) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    return text


def file_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def find_files(
    root: Path,
    pattern: str,
    *,
    recursive: bool = True,
    timeout: int = FIND_TIMEOUT_SECONDS,
) -> list[Path]:
    if not root.exists():
        return []
    args = ["find", str(root)]
    if not recursive:
        args.extend(["-maxdepth", "1"])
    args.extend(["-type", "f", "-name", pattern])
    try:
        result = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        return sorted(iterator)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def collapse_text(text: str, limit: int = 500) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: m.group(0).split("]")[0][1:], text)
    text = re.sub(r"[#>*_`~-]+", " ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "None"}:
        return ""
    if value == "[]":
        return []
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",")]
    return value.strip("\"'")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = idx
            break
    if end is None:
        return {}, text

    meta: dict[str, Any] = {}
    current_key: str | None = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_key:
            current = meta.setdefault(current_key, [])
            if isinstance(current, list):
                current.append(stripped[2:].strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        meta[current_key] = [] if not value.strip() else _parse_scalar(value)
    body = "\n".join(lines[end + 1 :])
    return meta, body


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text_with_digest(
    path: Path, max_bytes: int = MAX_TEXT_BYTES
) -> tuple[str, str]:
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"file too large for v0 backfill: {size} bytes")
    data = path.read_bytes()
    digest = __import__("hashlib").sha256(data).hexdigest()
    return data.decode("utf-8", errors="ignore"), digest


def backfill_image_gallery(
    gallery_dir: Path = IMAGE_GALLERY,
    *,
    limit: int | None = None,
    db_path: Path | None = None,
) -> BackfillStats:
    stats = BackfillStats()
    if not gallery_dir.exists():
        return stats

    with connect(db_path) as con:
        init_db(con)
        for png in sorted(find_files(gallery_dir, "*.png", recursive=False), reverse=True):
            if limit is not None and stats.scanned >= limit:
                break
            stats.scanned += 1
            try:
                sidecar = png.with_suffix(".json")
                metadata = read_json(sidecar) if sidecar.exists() else {}
                uri = file_uri(png)
                digest = hash_file(png)
                created_at = parse_loose_datetime(metadata.get("生成日時")) or file_mtime(png)
                title = str(metadata.get("入力プロンプト") or png.stem)
                prompt = str(
                    metadata.get("送信プロンプト")
                    or metadata.get("強化後プロンプト")
                    or title
                )
                run_id = stable_id("run", "image-generator", uri, digest)
                record_run(
                    app="image-generator",
                    action="backfill_gallery_image",
                    status="succeeded",
                    started_at=created_at,
                    ended_at=created_at,
                    model=str(metadata.get("チェックポイント") or ""),
                    params={"source": str(png), "sidecar": str(sidecar), **metadata},
                    run_id=run_id,
                    con=con,
                )
                result = record_artifact(
                    app="image-generator",
                    kind="image",
                    uri=uri,
                    sha256_value=digest,
                    run_id=run_id,
                    mime="image/png",
                    title=title,
                    excerpt=collapse_text(prompt),
                    created_at=created_at,
                    metadata={
                        "path": str(png),
                        "sidecar": str(sidecar) if sidecar.exists() else "",
                        **metadata,
                    },
                    con=con,
                )
                stats.artifacts_created += int(result.created)
                stats.artifacts_seen += 1
            except Exception as exc:  # keep backfill rerunnable despite bad files
                stats.errors.append(f"{png}: {exc}")
    return stats


def _source_refs(meta: dict[str, Any], body: str) -> list[str]:
    refs: list[str] = []
    raw = meta.get("source_refs", [])
    if isinstance(raw, str) and raw:
        refs.append(raw)
    elif isinstance(raw, list):
        refs.extend(str(item) for item in raw if str(item).strip())
    refs.extend(URL_RE.findall(body))
    return list(dict.fromkeys(ref.strip().rstrip(".,") for ref in refs if ref.strip()))


def _markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in find_files(root, "*.md", recursive=True)
        if "_trash" not in p.relative_to(root).parts
    )


def backfill_writing(
    writing_dir: Path = WRITING_DIR,
    zenn_articles_dir: Path = ZENN_ARTICLES_DIR,
    *,
    limit: int | None = None,
    max_text_bytes: int = MAX_TEXT_BYTES,
    db_path: Path | None = None,
) -> BackfillStats:
    stats = BackfillStats()
    files: list[tuple[str, Path]] = [
        ("draft", p) for p in _markdown_files(writing_dir)
    ]
    if zenn_articles_dir.exists():
        files.extend(
            ("zenn_article", p)
            for p in sorted(find_files(zenn_articles_dir, "*.md", recursive=False))
        )

    with connect(db_path) as con:
        init_db(con)
        for kind, path in files:
            if limit is not None and stats.scanned >= limit:
                break
            stats.scanned += 1
            try:
                text, digest = read_text_with_digest(path, max_text_bytes)
                meta, body = split_frontmatter(text)
                uri = file_uri(path)
                created_at = str(meta.get("created") or meta.get("date") or file_mtime(path))
                title = str(meta.get("title") or path.stem)
                run_id = stable_id("run", "writing", kind, uri, digest)
                record_run(
                    app="writing",
                    action=f"backfill_{kind}",
                    status="succeeded",
                    started_at=created_at,
                    ended_at=created_at,
                    params={"source": str(path), "frontmatter": meta},
                    run_id=run_id,
                    con=con,
                )
                result = record_artifact(
                    app="writing",
                    kind=kind,
                    uri=uri,
                    sha256_value=digest,
                    run_id=run_id,
                    mime="text/markdown",
                    title=title,
                    excerpt=collapse_text(body),
                    created_at=created_at,
                    metadata={"path": str(path), "frontmatter": meta},
                    con=con,
                )
                stats.artifacts_created += int(result.created)
                stats.artifacts_seen += 1
                for ref in _source_refs(meta, body):
                    src = record_source(
                        kind="url" if ref.startswith(("http://", "https://")) else "ref",
                        uri=ref,
                        raw_ref=ref,
                        con=con,
                    )
                    stats.sources_created += int(src.created)
                    link_artifact_source(result.id, src.id, role="reference", con=con)
            except Exception as exc:
                stats.errors.append(f"{path}: {exc}")
    return stats


def backfill_all(
    *,
    image_gallery: Path = IMAGE_GALLERY,
    writing_dir: Path = WRITING_DIR,
    zenn_articles_dir: Path = ZENN_ARTICLES_DIR,
    limit: int | None = None,
    max_text_bytes: int = MAX_TEXT_BYTES,
    db_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "image_generator": backfill_image_gallery(
            image_gallery, limit=limit, db_path=db_path
        ).as_dict(),
        "writing": backfill_writing(
            writing_dir,
            zenn_articles_dir,
            limit=limit,
            max_text_bytes=max_text_bytes,
            db_path=db_path,
        ).as_dict(),
        "finished_at": {"ts": now_utc()},
    }
