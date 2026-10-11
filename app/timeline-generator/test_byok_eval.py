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

    def test_no_overwrite_or_automatic_paid_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "already.json"
            path.write_text("existing")
            with patch.object(ev.getpass, "getpass", side_effect=AssertionError("Key input reached")):
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
                ev.main(["--route", "byok", "--theme", "昭和", "--max-usd", "0.50", "--output", str(output)])
            self.assertIn("Google AI Studio", prompt.call_args.args[0])
            self.assertIn("gemini-3.5-flash-lite", messages.getvalue())
            self.assertNotIn(key, messages.getvalue() + output.read_text())
            self.assertEqual(measure.call_args.args[2], key)


if __name__ == "__main__":
    unittest.main()
