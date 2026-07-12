from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app_hub.backfill import backfill_all, split_frontmatter
from app_hub.db import (
    connect,
    find_artifacts,
    hash_file,
    init_db,
    record_artifact,
    recent_artifacts,
)
from app_hub.hooks import record_image_gallery_save, record_writing_draft_save


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


if __name__ == "__main__":
    unittest.main()
