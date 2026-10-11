"""Exercise the import CLI against isolated sibling and unified snapshots."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ImportDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "midokoro-map"
        scripts = self.root / "scripts"
        scripts.mkdir(parents=True)
        self.script = scripts / "import-data.py"
        shutil.copyfile(Path(__file__).with_name("import-data.py"), self.script)
        source = base / "shiseki-map" / "frontend"
        source.mkdir(parents=True)
        (source / "shiseki.db").write_bytes(b"new database")
        self.target = self.root / "data" / "shiseki"
        self.target.mkdir(parents=True)
        self.manifest = self.root / "migration-manifest.json"

    def run_import(self, *flags):
        return subprocess.run(
            [sys.executable, str(self.script), "--kind", "shiseki", *flags],
            capture_output=True, text=True,
        )

    def test_database_only_records_existing_summaries_without_manifest_entry(self):
        summaries = {"summaries.json": b'{"unified":true}',
                     "official_summaries.json": b'{"official":true}'}
        for name, content in summaries.items():
            (self.target / name).write_bytes(content)
        result = self.run_import("--database-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = json.loads(self.manifest.read_text())["shiseki"]["files"]
        for name, content in summaries.items():
            self.assertEqual(files[name], hashlib.sha256(content).hexdigest())
            self.assertEqual((self.target / name).read_bytes(), content)
        self.assertEqual((self.target / "shiseki.db").read_bytes(), b"new database")

    def test_database_only_requires_replace_and_leaves_files_untouched(self):
        database = self.target / "shiseki.db"
        database.write_bytes(b"old database")
        self.manifest.write_text('{"unrelated": {}}\n')
        original_manifest = self.manifest.read_bytes()
        result = self.run_import("--database-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--replace", result.stderr)
        self.assertEqual(database.read_bytes(), b"old database")
        self.assertEqual(self.manifest.read_bytes(), original_manifest)
        result = self.run_import("--database-only", "--replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(database.read_bytes(), b"new database")

    def test_database_only_refreshes_stale_summary_hash(self):
        (self.target / "summaries.json").write_bytes(b"current summary")
        self.manifest.write_text(json.dumps({"shiseki": {"files": {
            "summaries.json": "stale", "other.json": "preserved"}}}))
        result = self.run_import("--database-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        files = json.loads(self.manifest.read_text())["shiseki"]["files"]
        self.assertEqual(files["summaries.json"], hashlib.sha256(b"current summary").hexdigest())
        self.assertEqual(files["other.json"], "preserved")


if __name__ == "__main__":
    unittest.main()
