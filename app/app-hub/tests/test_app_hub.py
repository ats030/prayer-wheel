from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app_hub.backfill import backfill_all, split_frontmatter
from app_hub.cli import doctor_report
from app_hub.db import (
    connect,
    find_artifacts,
    hash_file,
    init_db,
    record_artifact,
    recent_artifacts,
)
from app_hub.hooks import (
    record_image_gallery_save,
    record_writing_draft_save,
    record_writing_interview,
)


class DummyDraft:
    name = "draft"
    title = "Draft Title"
    form = "summary"
    technical = True
    status = "draft"
    source_refs = ["https://example.com/source"]
    theme = "記事テーマ"
    created = "2026-07-12 10:00"
    updated = "2026-07-12 10:10"


class AppHubTests(unittest.TestCase):
    def test_record_artifact_is_idempotent_by_uri_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "hub.sqlite"
            with connect(db) as con:
                init_db(con)
                first = record_artifact(
                    app="test",
                    kind="note",
                    uri="file:///tmp/a.md",
                    sha256_value="abc",
                    title="Alpha",
                    excerpt="first text",
                    con=con,
                )
                second = record_artifact(
                    app="test",
                    kind="note",
                    uri="file:///tmp/a.md",
                    sha256_value="abc",
                    title="Alpha updated",
                    excerpt="second text",
                    con=con,
                )
                rows = list(recent_artifacts(limit=10, con=con))
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.id, second.id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Alpha updated")

    def test_find_artifacts_uses_index_or_like_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "hub.sqlite"
            with connect(db) as con:
                init_db(con)
                record_artifact(
                    app="writing",
                    kind="draft",
                    uri="file:///tmp/duck.md",
                    sha256_value="abc",
                    title="DuckDB article",
                    excerpt="SQLite and DuckDB local analytics",
                    con=con,
                )
                record_artifact(
                    app="writing",
                    kind="draft",
                    uri="file:///tmp/data.md",
                    sha256_value="def",
                    title="データウェアハウス入門",
                    excerpt="大量データを扱う",
                    con=con,
                )
                rows = list(find_artifacts("DuckDB", limit=10, con=con))
                jp_rows = list(find_artifacts("データ", limit=10, con=con))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["app"], "writing")
            self.assertEqual(len(jp_rows), 1)
            self.assertEqual(jp_rows[0]["title"], "データウェアハウス入門")

    def test_split_frontmatter_parses_lists(self) -> None:
        meta, body = split_frontmatter(
            "---\n"
            "title: Sample\n"
            "source_refs:\n"
            "- https://example.com/a\n"
            "- local-note\n"
            "---\n"
            "Body"
        )
        self.assertEqual(meta["title"], "Sample")
        self.assertEqual(meta["source_refs"], ["https://example.com/a", "local-note"])
        self.assertEqual(body, "Body")

    def test_backfill_minimal_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hub.sqlite"
            gallery = root / "gallery"
            writing = root / "writing"
            zenn = root / "zenn"
            gallery.mkdir()
            writing.mkdir()
            zenn.mkdir()

            png = gallery / "20260712_000000_abcd.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            png.with_suffix(".json").write_text(
                json.dumps({"入力プロンプト": "猫", "送信プロンプト": "cat line art"}),
                encoding="utf-8",
            )
            draft = writing / "draft.md"
            draft.write_text(
                "---\ntitle: Draft Title\nsource_refs:\n- https://example.com\n---\n本文",
                encoding="utf-8",
            )
            article = zenn / "article.md"
            article.write_text("---\ntitle: Zenn Title\n---\n公開本文", encoding="utf-8")

            result = backfill_all(
                image_gallery=gallery,
                writing_dir=writing,
                zenn_articles_dir=zenn,
                db_path=db,
            )
            with connect(db) as con:
                rows = list(recent_artifacts(limit=10, con=con))
                sources = list(con.execute("SELECT * FROM sources"))

            self.assertEqual(result["image_generator"]["artifacts_seen"], 1)
            self.assertEqual(result["writing"]["artifacts_seen"], 2)
            self.assertEqual(len(rows), 3)
            self.assertEqual(len(sources), 1)
            self.assertEqual(hash_file(png), hash_file(png))

    def test_doctor_report_ok_with_temp_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hub.sqlite"
            data = root / "data"
            cache = root / "cache"
            gallery = root / "gallery"
            writing = root / "writing"
            zenn = root / "zenn"
            for path in (gallery, writing, zenn):
                path.mkdir()

            old_data = os.environ.get("APP_HUB_DATA_DIR")
            old_cache = os.environ.get("APP_HUB_CACHE_DIR")
            os.environ["APP_HUB_DATA_DIR"] = str(data)
            os.environ["APP_HUB_CACHE_DIR"] = str(cache)
            try:
                report = doctor_report(
                    db_path=db,
                    image_gallery=gallery,
                    writing_dir=writing,
                    zenn_articles_dir=zenn,
                )
            finally:
                if old_data is None:
                    os.environ.pop("APP_HUB_DATA_DIR", None)
                else:
                    os.environ["APP_HUB_DATA_DIR"] = old_data
                if old_cache is None:
                    os.environ.pop("APP_HUB_CACHE_DIR", None)
                else:
                    os.environ["APP_HUB_CACHE_DIR"] = old_cache

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["summary"]["errors"], 0)
            names = {check["name"] for check in report["checks"]}
            self.assertIn("database", names)
            self.assertIn("hooks_import", names)
            self.assertIn("error_log", names)

    def test_hooks_record_without_full_body_or_prompt_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hub.sqlite"
            old_db = os.environ.get("APP_HUB_DB_PATH")
            os.environ["APP_HUB_DB_PATH"] = str(db)
            try:
                draft = root / "draft.md"
                body = "本文です。https://example.com/body も参照します。"
                draft.write_text("---\ntitle: Draft Title\n---\n" + body, encoding="utf-8")
                record_writing_draft_save(draft, DummyDraft(), body)

                png = root / "image.png"
                png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
                sidecar = root / "image.json"
                params = {
                    "生成日時": "2026-07-12 10:20:00",
                    "入力プロンプト": "猫の線画",
                    "送信プロンプト": "cat line art with a very specific full prompt",
                    "送信ネガティブ": "low quality",
                    "チェックポイント": "sd_xl_base",
                }
                sidecar.write_text(json.dumps(params), encoding="utf-8")
                record_image_gallery_save(png, sidecar, params)
            finally:
                if old_db is None:
                    os.environ.pop("APP_HUB_DB_PATH", None)
                else:
                    os.environ["APP_HUB_DB_PATH"] = old_db

            with connect(db) as con:
                rows = list(recent_artifacts(limit=10, con=con))
                metadata = "\n".join(
                    row["metadata_json"]
                    for row in con.execute("SELECT metadata_json FROM artifacts")
                )
                sources = list(con.execute("SELECT * FROM sources"))

            self.assertEqual(len(rows), 2)
            self.assertEqual(len(sources), 2)
            self.assertNotIn(body, metadata)
            self.assertNotIn("cat line art with a very specific full prompt", metadata)

    def test_interview_hook_records_an_artifact_per_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "hub.sqlite"
            old_db = os.environ.get("APP_HUB_DB_PATH")
            os.environ["APP_HUB_DB_PATH"] = str(db)
            try:
                sidecar = root / "取材メモ.md"
                sidecar.write_text("---\nquestions: []\n---\n本文", encoding="utf-8")
                record_writing_interview(
                    sidecar,
                    target="article:記事",
                    title="記事",
                    counts={"open": 2, "answered": 1, "dismissed": 0},
                    answered_entries=[
                        {"question": "何回失敗しましたか", "answer": "17回です"}
                    ],
                )
            finally:
                if old_db is None:
                    os.environ.pop("APP_HUB_DB_PATH", None)
                else:
                    os.environ["APP_HUB_DB_PATH"] = old_db

            with connect(db) as con:
                rows = list(recent_artifacts(limit=10, con=con))
                metadata = "\n".join(
                    row["metadata_json"]
                    for row in con.execute("SELECT metadata_json FROM artifacts")
                )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["kind"], "interview")
            self.assertIn("取材メモ: 記事", rows[0]["title"])
            self.assertIn("article:記事", metadata)
            self.assertIn('"author_answers": 1', metadata)

    def test_interview_hook_never_raises_on_a_missing_file(self) -> None:
        # 失敗はエラーログ行になるので、利用者の ~/.cache を汚さないよう逃がす。
        with tempfile.TemporaryDirectory() as tmp:
            old_cache = os.environ.get("APP_HUB_CACHE_DIR")
            os.environ["APP_HUB_CACHE_DIR"] = tmp
            try:
                record_writing_interview(
                    Path(tmp) / "missing" / "取材メモ.md",
                    target="article:記事",
                    title="記事",
                    counts={},
                )
            finally:
                if old_cache is None:
                    os.environ.pop("APP_HUB_CACHE_DIR", None)
                else:
                    os.environ["APP_HUB_CACHE_DIR"] = old_cache

            self.assertTrue((Path(tmp) / "error.log").exists())


if __name__ == "__main__":
    unittest.main()
