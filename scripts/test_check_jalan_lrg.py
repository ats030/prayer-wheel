"""Tests for check-jalan-lrg.py record rules and shared-QID handling.

The checker's job after the Shiseki expansion is to validate *assignments that
already exist* without assuming either a fixed prefecture table (multi-prefecture
sites) or QID uniqueness across apps (shared Wikidata items). These tests pin down
that multi-prefecture and shared-QID normal cases pass, and that an unassigned
code or an inconsistent shared-QID assignment still fails.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("check_jalan_lrg", _HERE / "check-jalan-lrg.py")
_ck = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ck)


def _valid_record(qid, prefs="大阪府"):
    code, name = "273800", "大阪南部（堺・岸和田・関西空港）"
    sml_code, sml_name = "273820", "堺市"
    return {
        "id": qid,
        "prefecture": prefs,
        "jalan_lrg_code": code,
        "jalan_lrg_name": name,
        "jalan_sml_code": sml_code,
        "jalan_sml_name": sml_name,
    }


def _overrides_for(record):
    qid = record["id"]
    code, name = record["jalan_lrg_code"], record["jalan_lrg_name"]
    sml_code, sml_name = record["jalan_sml_code"], record["jalan_sml_name"]
    lrg = {qid: {
        "code": code,
        "name": name,
        "evidence": {
            "official_url": f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/",
            "confirmed_at": "2026-01-01",
            "method": "jalan-official-area-xml",
        },
    }}
    sml = {qid: {
        "lrg_code": code,
        "sml_code": sml_code,
        "sml_name": sml_name,
        "evidence": {
            "official_url": f"https://www.jalan.net/{code[:2]}0000/LRG_{code}/SML_{sml_code}/",
            "confirmed_at": "2026-01-01",
            "method": "jalan-official-area-xml",
        },
    }}
    return lrg, sml


def _run_check_record(record):
    lrg, sml = _overrides_for(record)
    errors = []
    _ck.check_record(record, lrg, sml, errors)
    return errors


class MultiPrefectureTest(unittest.TestCase):
    def test_multi_prefecture_valid_code_passes(self):
        record = _valid_record("Q1")
        record["prefecture"] = _ck.MULTI_PREF
        self.assertEqual(_run_check_record(record), [])

    def test_single_prefecture_valid_code_passes(self):
        self.assertEqual(_run_check_record(_valid_record("Q1")), [])


class SharedQidTest(unittest.TestCase):
    def _dataset_file(self, record):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump([record], tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_shared_qid_consistent_assignment_passes(self):
        record = _valid_record("Q1")
        lrg, sml = _overrides_for(record)
        datasets = [self._dataset_file(record), self._dataset_file(record)]
        errors, _total, _unassigned, _assigned = _ck.check_all(datasets, lrg, sml)
        self.assertEqual(errors, [])

    def test_shared_qid_inconsistent_assignment_fails(self):
        a = _valid_record("Q1")
        b = _valid_record("Q1")
        b["prefecture"] = "東京都"
        b["jalan_lrg_code"] = "130700"
        b["jalan_lrg_name"] = "多摩"
        b["jalan_sml_code"] = "130720"
        b["jalan_sml_name"] = "八王子"
        lrg_a, sml_a = _overrides_for(a)
        datasets = [self._dataset_file(a), self._dataset_file(b)]
        errors, _total, _unassigned, _assigned = _ck.check_all(datasets, lrg_a, sml_a)
        self.assertTrue(any("inconsistent region assignments" in e for e in errors), errors)


class UnassignedCodeTest(unittest.TestCase):
    def test_missing_lrg_code_fails(self):
        record = _valid_record("Q1")
        record["jalan_lrg_code"] = ""
        record["jalan_lrg_name"] = ""
        record["jalan_sml_code"] = ""
        record["jalan_sml_name"] = ""
        lrg, sml = _overrides_for(_valid_record("Q1"))
        errors = []
        _ck.check_record(record, lrg, sml, errors)
        self.assertTrue(any("malformed or missing code" in e for e in errors), errors)


class MainContractTest(unittest.TestCase):
    def test_check_reports_unassigned_and_key_diff_counts(self):
        record = _valid_record("Q1")
        lrg, sml = _overrides_for(record)
        lrg["Q_STALE"] = {"code": "273800", "name": "stale"}
        sml["Q_STALE"] = {"lrg_code": "273800", "sml_code": "273820", "sml_name": "stale"}
        unassigned = _valid_record("Q2")
        unassigned["jalan_lrg_code"] = ""
        unassigned["jalan_lrg_name"] = ""
        unassigned["jalan_sml_code"] = ""
        unassigned["jalan_sml_name"] = ""

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump([record, unassigned], tmp, ensure_ascii=False)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)

        result = _ck.check([Path(tmp.name)], lrg, sml)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["assigned"], 1)
        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(result["stale_lrg_overrides"], ["Q_STALE"])
        self.assertEqual(result["missing_lrg_overrides"], [])


if __name__ == "__main__":
    unittest.main()
