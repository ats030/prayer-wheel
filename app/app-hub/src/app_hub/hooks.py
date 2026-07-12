from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Any

from app_hub import config
from app_hub.db import (
    connect,
    file_uri,
    hash_file,
    init_db,
    link_artifact_source,
    now_utc,
    record_artifact,
    record_event,
    record_run,
    record_source,
    stable_id,
)

URL_RE = re.compile(r"https?://[^\s<>)\"']+")


def _collapse_text(text: str, limit: int = 500) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: m.group(0).split("]")[0][1:], text)
    text = re.sub(r"[#>*_`~-]+", " ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _log_hook_error(label: str, exc: BaseException) -> None:
    try:
        config.log_error(
            f"{now_utc()} {label}: {type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc(limit=6).rstrip()}"
        )
    except Exception:
        pass


def _safe_record(label: str, fn) -> None:
    try:
        fn()
    except Exception as exc:
        _log_hook_error(label, exc)


def _source_refs(*parts: object) -> list[str]:
    refs: list[str] = []
    for part in parts:
        if not part:
            continue
        if isinstance(part, (list, tuple, set)):
            refs.extend(str(item) for item in part if str(item).strip())
            continue
        text = str(part)
        refs.extend(URL_RE.findall(text))
    return list(dict.fromkeys(ref.strip().rstrip(".,") for ref in refs if ref.strip()))


def _record_sources(con, artifact_id: str, refs: list[str]) -> None:
    for ref in refs:
        src = record_source(
            kind="url" if ref.startswith(("http://", "https://")) else "ref",
            uri=ref,
            raw_ref=ref,
            con=con,
        )
        link_artifact_source(artifact_id, src.id, role="reference", con=con)


def _image_metadata(
    params: dict[str, Any], png_path: Path, sidecar_path: Path
) -> dict[str, Any]:
    keep_keys = (
        "生成日時",
        "テイスト",
        "バナー構図",
        "塗り絵仕上げ",
        "Ollamaフォールバック",
        "チェックポイント",
        "サンプラー",
        "シード",
        "サイズ",
        "候補",
    )
    data = {key: params.get(key) for key in keep_keys if key in params}
    data.update({"path": str(png_path), "sidecar": str(sidecar_path)})
    return data


def record_image_gallery_save(
    png_path: Path | str,
    sidecar_path: Path | str,
    params: dict[str, Any],
) -> None:
    """Best-effort record for an image-generator gallery save."""

    def _record() -> None:
        png = Path(png_path)
        sidecar = Path(sidecar_path)
        prompt = str(
            params.get("送信プロンプト")
            or params.get("強化後プロンプト")
            or params.get("入力プロンプト")
            or ""
        )
        title = str(params.get("入力プロンプト") or png.stem)
        created_at = str(params.get("生成日時") or "")
        digest = hash_file(png)
        uri = file_uri(png)
        metadata = _image_metadata(params, png, sidecar)
        with connect() as con:
            init_db(con)
            run_id = stable_id(
                "run", "image-generator", "save_gallery_image", uri, digest
            )
            record_run(
                app="image-generator",
                action="save_gallery_image",
                status="succeeded",
                started_at=created_at,
                ended_at=created_at,
                model=str(params.get("チェックポイント") or ""),
                params=metadata,
                run_id=run_id,
                con=con,
            )
            record_artifact(
                app="image-generator",
                kind="image",
                uri=uri,
                sha256_value=digest,
                run_id=run_id,
                mime="image/png",
                title=_collapse_text(title, 160),
                excerpt=_collapse_text(prompt),
                created_at=created_at,
                metadata=metadata,
                con=con,
            )

    _safe_record("record_image_gallery_save", _record)


def _draft_metadata(
    draft: object, body: str, path: Path, source_refs: list[str]
) -> dict[str, Any]:
    theme = str(getattr(draft, "theme", "") or "")
    return {
        "path": str(path),
        "name": str(getattr(draft, "name", path.stem)),
        "form": str(getattr(draft, "form", "")),
        "technical": bool(getattr(draft, "technical", False)),
        "status": str(getattr(draft, "status", "")),
        "created": str(getattr(draft, "created", "")),
        "updated": str(getattr(draft, "updated", "")),
        "body_chars": len(body),
        "source_ref_count": len(source_refs),
        "theme_excerpt": _collapse_text(theme, 240) if theme else "",
    }


def record_writing_draft_save(path: Path | str, draft: object, body: str) -> None:
    """Best-effort record for a writing workshop draft save."""

    def _record() -> None:
        draft_path = Path(path)
        source_refs = _source_refs(getattr(draft, "source_refs", []), body)
        digest = hash_file(draft_path)
        uri = file_uri(draft_path)
        title = str(getattr(draft, "title", "") or draft_path.stem)
        created_at = str(
            getattr(draft, "updated", "") or getattr(draft, "created", "") or ""
        )
        metadata = _draft_metadata(draft, body, draft_path, source_refs)
        with connect() as con:
            init_db(con)
            run_id = stable_id("run", "writing", "save_draft", uri, digest)
            record_run(
                app="writing",
                action="save_draft",
                status="succeeded",
                started_at=created_at,
                ended_at=created_at,
                params=metadata,
                run_id=run_id,
                con=con,
            )
            artifact = record_artifact(
                app="writing",
                kind="draft",
                uri=uri,
                sha256_value=digest,
                run_id=run_id,
                mime="text/markdown",
                title=title,
                excerpt=_collapse_text(body),
                created_at=created_at,
                metadata=metadata,
                con=con,
            )
            _record_sources(con, artifact.id, source_refs)

    _safe_record("record_writing_draft_save", _record)


def record_writing_export(
    path: Path | str,
    draft: object,
    body: str,
    meta: dict[str, Any],
    *,
    slug: str,
    warnings: list[str] | None = None,
    images_copied: list[str] | None = None,
) -> None:
    """Best-effort record for a Zenn article export."""

    def _record() -> None:
        article_path = Path(path)
        source_refs = _source_refs(getattr(draft, "source_refs", []), body)
        digest = hash_file(article_path)
        uri = file_uri(article_path)
        title = str(
            meta.get("title") or getattr(draft, "title", "") or article_path.stem
        )
        metadata = {
            "path": str(article_path),
            "slug": slug,
            "type": str(meta.get("type", "")),
            "topics": list(meta.get("topics") or []),
            "published": bool(meta.get("published", False)),
            "warnings_count": len(warnings or []),
            "images_copied_count": len(images_copied or []),
            "source_ref_count": len(source_refs),
        }
        with connect() as con:
            init_db(con)
            run_id = stable_id("run", "writing", "export_zenn_article", uri, digest)
            record_run(
                app="writing",
                action="export_zenn_article",
                status="succeeded",
                started_at=now_utc(),
                ended_at=now_utc(),
                params=metadata,
                run_id=run_id,
                con=con,
            )
            artifact = record_artifact(
                app="writing",
                kind="zenn_article",
                uri=uri,
                sha256_value=digest,
                run_id=run_id,
                mime="text/markdown",
                title=title,
                excerpt=_collapse_text(body),
                created_at=now_utc(),
                metadata=metadata,
                con=con,
            )
            _record_sources(con, artifact.id, source_refs)

    _safe_record("record_writing_export", _record)


def record_writing_publish_result(
    slug: str,
    status: str,
    message: str,
    *,
    article_path: Path | str | None = None,
) -> None:
    """Best-effort record for a publish attempt."""

    def _record() -> None:
        normalized = "succeeded" if status == "succeeded" else "failed"
        params = {
            "slug": slug,
            "path": str(article_path) if article_path else "",
            "message_excerpt": _collapse_text(message, 300),
        }
        with connect() as con:
            init_db(con)
            run_id = stable_id(
                "run",
                "writing",
                "publish_zenn_article",
                slug,
                normalized,
                params["message_excerpt"],
            )
            record_run(
                app="writing",
                action="publish_zenn_article",
                status=normalized,
                started_at=now_utc(),
                ended_at=now_utc(),
                params=params,
                error=message if normalized != "succeeded" else None,
                run_id=run_id,
                con=con,
            )
            if normalized != "succeeded":
                record_event(
                    app="writing",
                    level="error",
                    message="publish_zenn_article failed",
                    run_id=run_id,
                    context=params,
                    con=con,
                )

    _safe_record("record_writing_publish_result", _record)
