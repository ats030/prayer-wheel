import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scale_experiment


def row(qid, name, prefecture="東京都", **overrides):
    value = {
        "qid": qid, "label_ja": name, "prefecture": prefecture,
        "latitude": 35.68, "longitude": 139.76, "categories": ["城跡"],
        "designation": "national", "description": "", "source_url": f"https://www.wikidata.org/wiki/{qid}",
    }
    value.update(overrides)
    return value


class ScaleExperimentTest(unittest.TestCase):
    def test_ingest_separates_evidence_and_flags_conservative_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = scale_experiment.create_database(Path(directory) / "pilot.db")
            report = scale_experiment.ingest(connection, [row("Q1", "江戸城"), row("Q2", "江戸 城")], ("東京都",))
            self.assertEqual(report["published"], 2)
            self.assertEqual(report["duplicate_candidates"], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM place_sources").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT reason FROM review_queue").fetchone()[0], "possible_duplicate")

    def test_missing_provenance_is_held(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = scale_experiment.create_database(Path(directory) / "pilot.db")
            report = scale_experiment.ingest(connection, [row("Q1", "出典なし", source_url="")], ("東京都",))
            self.assertEqual(report, {"selected": 1, "published": 0, "held": 1, "duplicate_candidates": 0})
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM places").fetchone()[0], 0)

    def test_qid_is_optional_and_designation_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = scale_experiment.create_database(Path(directory) / "pilot.db")
            item = row("", "管理番号だけの史跡", designation_source="https://example.jp/designation/1")
            report = scale_experiment.ingest(connection, [item], ("東京都",))
            self.assertEqual(report["published"], 1)
            self.assertTrue(connection.execute("SELECT canonical_id FROM places").fetchone()[0].startswith("snapshot:"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM external_ids").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM place_sources").fetchone()[0], 2)

    def test_run_builds_benchmark_without_changing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source.json"
            source.write_text(json.dumps([row("Q1", "江戸城")], ensure_ascii=False), encoding="utf-8")
            report = scale_experiment.run(source, base / "pilot.db", ("東京都",), 100)
            self.assertEqual(report["benchmark_records"], 100)
            self.assertEqual(report["supply_verdict"], "unproven")
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))[0]["qid"], "Q1")

    def test_run_refuses_to_overwrite_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            source.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                scale_experiment.run(source, source, ("東京都",), 100)


if __name__ == "__main__":
    unittest.main()
