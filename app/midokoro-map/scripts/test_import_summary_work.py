import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


class ImportSummaryWorkTest(unittest.TestCase):
    def test_merge_preserves_legacy_unified_and_work_and_rejects_bad_input(self):
        spec = importlib.util.spec_from_file_location(
            "import_summary_work", Path(__file__).with_name("import-summary-work.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app/midokoro-map"
            module.ROOT, module.WORK = root, root / "data/summary-work"
            for kind in ("shiseki", "omatsuri", "onsen", "tokusan"):
                for base, value in ((root.parent / f"{kind}-map/data", {"old": "old"}),
                                    (root / "data" / kind, {"unified": "new"}),
                                    (module.WORK / "cache" / kind, {"work": "generated"})):
                    base.mkdir(parents=True, exist_ok=True)
                    (base / "summaries.json").write_text(json.dumps(value))
                    if kind == "tokusan":
                        section = "history" if "old" in value else "production" if "unified" in value else "about"
                        (base / "official_summaries.json").write_text(json.dumps({"Q1": {"sections": {section: {"summary": section}}}}))
            module.main()
            target = module.WORK / "cache/shiseki/summaries.json"
            expected = {"old": "old", "unified": "new", "work": "generated"}
            self.assertEqual(json.loads(target.read_text()), expected)
            official = json.loads((module.WORK / "cache/tokusan/official_summaries.json").read_text())
            self.assertEqual(set(official["Q1"]["sections"]), {"history", "production", "about"})
            wiki = json.loads((module.WORK / "cache/tokusan/summaries.json").read_text())
            self.assertNotIn("midokoro-official-source-v2:Q1:history", wiki)
            module.main()
            self.assertEqual(json.loads(target.read_text()), expected)
            (root.parent / "onsen-map/data/summaries.json").write_text("broken")
            with self.assertRaises(json.JSONDecodeError):
                module.main()
            self.assertEqual(json.loads(target.read_text()), expected)


if __name__ == "__main__":
    unittest.main()
