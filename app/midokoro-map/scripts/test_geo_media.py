#!/usr/bin/env python3
"""Run the geo detail media tests (test-geo-media.mjs) under Node from a Python test.

The Ollama draft runner accepts only Python test commands.
"""
from pathlib import Path
import subprocess
import unittest


class GeoMedia(unittest.TestCase):
    def test_node_suite_passes(self):
        result = subprocess.run(["node", "--test", str(Path(__file__).with_name("test-geo-media.mjs"))], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
