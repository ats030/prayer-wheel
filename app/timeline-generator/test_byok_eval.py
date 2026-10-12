import copy
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import byok_eval as ev


class EvaluationTests(unittest.TestCase):
    def test_key_file_supports_literal_quotes_comments_and_never_executes(self):
        key = "AIza" + "x" * 35
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            marker = Path(directory) / "must-not-exist"
            for assignment in (f"GEMINI_API_KEY={key}", f'export GEMINI_API_KEY="{key}" # comment',
                               f"GEMINI_API_KEY='{key}'"):
                path.write_text(f"OTHER=$(touch {marker})\n{assignment}\n")
                self.assertEqual(ev.read_key_file(path, "GEMINI_API_KEY"), key)
                self.assertFalse(marker.exists())
            path.write_text(f"GEMINI_API_KEY=$(touch {marker})\n")
            with self.assertRaises(ev.ByokError):
                ev.read_key_file(path, "GEMINI_API_KEY")
            self.assertFalse(marker.exists())

    def test_key_file_missing_invalid_duplicate_errors_do_not_echo_secrets(self):
        key = "AIza" + "x" * 35
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            for content, code in (("OTHER=value\n", "key_variable_missing"),
                                  (f"GEMINI_API_KEY={key}\nGEMINI_API_KEY={key}\n", "key_variable_duplicate"),
                                  (f'GEMINI_API_KEY="{key}\n', "key_file_invalid"),
                                  ("GEMINI_API_KEY=invalid\n", "invalid_api_key")):
                path.write_text(content)
                with self.assertRaises(ev.ByokError) as error:
                    ev.read_key_file(path, "GEMINI_API_KEY")
                self.assertEqual(error.exception.code, code)
                self.assertNotIn(key, str(error.exception))

    def test_key_file_cli_is_noninteractive_and_does_not_export_key_or_file(self):
        key = "AIza" + "x" * 35
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text(f"GEMINI_API_KEY={key}\n")
            output = Path(directory) / "report.json"
            with patch.object(ev.os, "isatty", return_value=False), \
                 patch.object(ev.getpass, "getpass", side_effect=AssertionError("Prompt reached")), \
                 patch.object(ev, "measure", return_value={"passed": False}) as measure, \
                 contextlib.redirect_stdout(io.StringIO()) as messages:
                ev.main(["--route", "byok", "--theme", "昭和", "--max-usd", "0.50",
                         "--key-env-file", str(env), "--output", str(output)])
            self.assertEqual(measure.call_args.args[2], key)
            self.assertNotIn(key, messages.getvalue() + output.read_text())
            self.assertEqual(env.read_text(), f"GEMINI_API_KEY={key}\n")
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_missing_file_key_stops_before_output_creation_or_provider_call(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text("OTHER=value\n")
            output = Path(directory) / "report.json"
            with patch.object(ev, "measure", side_effect=AssertionError("Provider reached")), \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ev.main(["--route", "byok", "--theme", "昭和", "--max-usd", "0.50",
                             "--key-env-file", str(env), "--output", str(output)])
            self.assertFalse(output.exists())

    def test_failed_measurement_keeps_last_material_snapshot_and_filter(self):
        def generate(theme, key, options, emit, stopping):
            emit({"kind": "usage", "usage": {"calls": 1},
                  "material": {"sources_fetched": 2, "batches_total": 9}})
            emit({"kind": "usage", "usage": {"calls": 2}})
            emit({"kind": "ended", "error": "call_budget"})
        with patch.object(ev, "bounded_byok", side_effect=generate), \
             patch.dict(ev.os.environ, {"TIMELINE_FOOTNOTE_FILTER": "1"}):
            report = ev.measure("昭和", "byok", None, {})
        self.assertEqual(report["error"], "call_budget")
        self.assertEqual(report["usage"], {"calls": 2})
        self.assertEqual(report["material"], {"sources_fetched": 2, "batches_total": 9})
        self.assertEqual(report["conditions"]["footnote_filter"], "1")
        self.assertFalse(report["passed"])

    def test_explicit_larger_call_cap_keeps_cost_time_and_rate_limits(self):
        standard = ev.configuration(3600, 500000)
        larger = ev.configuration(3600, 500000, 100)
        self.assertEqual(standard["model_calls"], 60)
        self.assertEqual(larger, {**standard, "model_calls": 100})
        for cap in (0, 101, True):
            with self.assertRaises(ValueError):
                ev.configuration(3600, 500000, cap)

    def test_spawn_entry_does_not_preload_timeline_source_configuration(self):
        check = subprocess.run([sys.executable, "-c",
            "import sys; import byok_eval; assert 'timeline' not in sys.modules"],
            cwd=ev.ROOT, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_matching_conditions_only_and_failed_cases_stay_in_comparison(self):
        left = {"route": "byok", "theme": "昭和", "conditions": {"sha256": "fixed"}, "passed": False}
        right = {**copy.deepcopy(left), "route": "operator", "passed": True}
        self.assertFalse(ev.compare(left, right)["passed"])
        right["conditions"]["sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "conditions must match"):
            ev.compare(left, right)

    def test_measurement_code_changes_cannot_pass_or_compare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "byok.py").write_text("initial")
            for name in ("quality_gold.json", "quality_holdout.json"):
                (root / name).write_text(json.dumps({"themes": {"昭和": {}}}))
            def generate(theme, key, options, emit, stopping):
                (root / "byok.py").write_text("changed")
                emit({"kind": "result", "stop_reason": "sources_exhausted"})
            with patch.object(ev, "ROOT", root), patch.object(ev, "HASHED", ("byok.py",)), \
                 patch.object(ev, "bounded_byok", side_effect=generate), \
                 patch("quality_eval.evaluate_result", return_value={"recall": 1, "known_errors": [], "duplicates": []}), \
                 patch.object(ev, "result_view", return_value={}):
                report = ev.measure("昭和", "byok", None, {})
            self.assertFalse(report["passed"])
            self.assertEqual(report["error"], "code_changed")
            self.assertEqual(report["conditions"]["sha256"]["byok.py"], ev.hashlib.sha256(b"initial").hexdigest())
            with self.assertRaisesRegex(ValueError, "Code changed"):
                ev.compare(report, {**report, "route": "operator"})

    def test_no_overwrite_or_automatic_paid_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "already.json"
            path.write_text("existing")
            with patch.object(ev.getpass, "getpass", side_effect=AssertionError("Key input reached")), \
                 patch.object(ev, "read_key_file", side_effect=AssertionError("Key file reached")):
                with self.assertRaises(SystemExit):
                    ev.main(["--output", str(path), "--route", "byok", "--theme", "昭和", "--max-usd", "0.50"])
            self.assertEqual(path.read_text(), "existing")

    def test_explicit_comparison_requires_no_key_or_generation_and_private_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for route in ("operator", "byok"):
                (root / (route + ".json")).write_text(json.dumps({"route": route, "theme": "昭和", "conditions": {}, "passed": False}))
            output = root / "comparison.json"
            with patch.object(ev, "measure", side_effect=AssertionError("Generation reached")):
                self.assertEqual(ev.main(["--output", str(output), "--compare", str(root / "operator.json"), str(root / "byok.json")]), 1)
            self.assertFalse(json.loads(output.read_text())["passed"])
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_default_key_prompt_and_model_are_google(self):
        key = "AIza" + "x" * 35
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "google.json"
            with patch.object(ev.os, "isatty", return_value=True), \
                 patch.object(ev.getpass, "getpass", return_value=key) as prompt, \
                 patch.object(ev, "measure", return_value={"passed": False}) as measure, \
                 contextlib.redirect_stdout(io.StringIO()) as messages:
                ev.main(["--route", "byok", "--theme", "昭和", "--max-usd", "0.50", "--prompt-key", "--output", str(output)])
            self.assertIn("Google AI Studio", prompt.call_args.args[0])
            self.assertIn("gemini-3.5-flash-lite", messages.getvalue())
            self.assertNotIn(key, messages.getvalue() + output.read_text())
            self.assertEqual(measure.call_args.args[2], key)


if __name__ == "__main__":
    unittest.main()
