import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_cloudflare_app as build


class AppBuildTests(unittest.TestCase):
    def test_only_shared_assets_and_displayed_public_fields_are_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            (snapshot / "showa").mkdir(parents=True)
            (root / "cloudflare").mkdir()
            event = '<li class="event"><div class="event-date">1926年</div><h3 class="event-title">公開済み</h3><p class="event-description">説明 &amp; 本文</p><a class="source-link" href="https://ja.wikipedia.org/wiki/Test" title="記事">出典</a></li>'
            html = "<ol>" + event * 50 + "</ol>"
            (snapshot / "showa/index.html").write_text(html)
            hashes = {"showa/index.html": hashlib.sha256(html.encode()).hexdigest()}
            for name in ("index.html", "tokens.css", "styles.css", "favicon.svg"):
                (snapshot / name).write_text("published asset")
                hashes[name] = hashlib.sha256(b"published asset").hexdigest()
            (root / "cloudflare/published-snapshot-sha256.json").write_text(json.dumps(hashes))
            (root / "cloudflare/app-headers.txt").write_text("/*\n X-Content-Type-Options: nosniff\n")
            for name in build.FILES:
                (root / name).write_text("<html>shared" + build.LOCAL_LOG + "</html>" if name.endswith(".html") else "shared asset")
            (root / "private.sqlite3").write_text("private DB")
            (root / ".env").write_text("PRIVATE_SECRET=secret-value")
            with patch.object(build, "ROOT", root), patch.object(build, "PUBLISHED_SNAPSHOT", snapshot):
                build.build_app()
                output = root / "cloudflare/app-assets"
                files = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
                self.assertEqual(files, {*build.FILES, "published/showa.json", "_headers"})
                job = json.loads((output / "published/showa.json").read_text())
                self.assertTrue(job["read_only"])
                self.assertEqual(job["result"]["source_mode"], "unknown")
                self.assertIsNone(job["generated_at"])
                self.assertEqual(job["result"]["events"][0]["description"], "説明 & 本文")
                self.assertNotIn("quote", job["result"]["events"][0])
                self.assertNotIn("ubuntu-server-app", (output / "index.html").read_text())
                self.assertIn(build.LOCAL_LOG, (root / "index.html").read_text())
                previous = (output / "published/showa.json").read_bytes()
                (snapshot / "showa/index.html").write_text("changed publication")
                with self.assertRaisesRegex(ValueError, "content changed"):
                    build.build_app()
                self.assertEqual((output / "published/showa.json").read_bytes(), previous)

    def test_public_source_and_event_validation(self):
        for url in ("http://ja.wikipedia.org/wiki/Test", "https://private.example/data", "https://user:password@ja.wikipedia.org/wiki/Test"):
            with self.assertRaisesRegex(ValueError, "published source"):
                build.PublishedEvents().feed(f'<li class="event"><a class="source-link" href="{url}" title="source"></a></li>')
        with self.assertRaisesRegex(ValueError, "fields changed"):
            build.PublishedEvents().feed('<li class="event"><div class="event-date">1926年</div></li>')
