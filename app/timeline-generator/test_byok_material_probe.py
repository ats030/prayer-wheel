import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

import timeline


class ProbeTests(unittest.TestCase):
    def test_offline_probe_does_not_connect_provider_or_export_material(self):
        source = {"title": "昭和", "url": "https://ja.wikipedia.org/wiki/Showa",
                  "text": "1926年、SECRET本文。", "passages": [
                      {"text": "1926年、SECRET本文。", "heading": "歴史", "date_heading": "1926年"}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe.json"
            script = Path(__file__).with_name("byok_material_probe.py")
            with patch.object(sys, "argv", [str(script), "--output", str(output)]), \
                 patch.object(timeline, "search", return_value=[]), \
                 patch.object(timeline, "fetch_sources", return_value=[source]), \
                 patch.object(timeline, "material_batches", return_value=iter([[source]])), \
                 patch.object(timeline, "json_request"), patch.object(timeline.WebReader, "request"), \
                 patch("byok.transport", side_effect=AssertionError("Provider reached")), \
                 contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(str(script), run_name="__main__")
            report = json.loads(output.read_text())
            self.assertEqual(report["provider_calls"], 0)
            self.assertEqual(report["material"]["batches_total"], 1)
            self.assertEqual(report["planned_generate_payloads"], 1)
            self.assertGreater(report["planned_generate_payload_bytes"], 0)
            self.assertNotIn("SECRET", output.read_text())
            self.assertNotIn("AIza", output.read_text())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
