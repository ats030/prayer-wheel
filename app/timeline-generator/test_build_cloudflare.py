import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_cloudflare as build


class SnapshotTests(unittest.TestCase):
    def test_fixed_snapshot_validated_before_replacing_previous_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            cloudflare = root / "cloudflare"
            cloudflare.mkdir()
            (cloudflare / "headers.txt").write_text("/*\n  X-Content-Type-Options: nosniff\n")
            bodies = {"index.html": b"<html>index</html>", "showa/index.html": b"<html>showa</html>",
                      **{name: b"asset" for name in build.ASSETS}}
            for name, body in bodies.items():
                path = snapshot / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            (snapshot / "private.sqlite3").write_text("SECRET")
            (cloudflare / "published-snapshot-sha256.json").write_text(json.dumps(
                {name: hashlib.sha256(body).hexdigest() for name, body in bodies.items()}))
            with patch.object(build, "ROOT", root), patch.object(build, "PUBLISHED_SNAPSHOT", snapshot):
                build.build_public(True)
                output = cloudflare / "assets"
                self.assertFalse((output / "private.sqlite3").exists())
                self.assertEqual((output / "showa/index.html").read_bytes(), bodies["showa/index.html"])
                (snapshot / "showa/index.html").write_text("changed")
                with self.assertRaisesRegex(ValueError, "content changed"):
                    build.build_public(True)
                self.assertEqual((output / "showa/index.html").read_bytes(), bodies["showa/index.html"])


if __name__ == "__main__":
    unittest.main()
