import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "failure_message", Path(__file__).with_name("notify_failure_message.py"))
formatter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(formatter)


class MessageTests(unittest.TestCase):
    def test_states_and_unknown_cause(self):
        for result, expected in (("timeout", "制限時間"), ("exit-code", "エラー"),
                                 ("signal", "シグナル"), ("start-limit-hit", "起動回数"),
                                 ("unexpected", "詳細はログ")):
            text = formatter.message("backlog-enrich.service", "週次棚卸し", result,
                                     "9", "observed error", "2026-10-07")
            self.assertIn(expected, text)
            self.assertIn("週次タスク棚卸し", text)
            self.assertIn("journalctl --user -u backlog-enrich.service", text)
        self.assertIn("signal=9", formatter.message("a.service", "", "signal", "9", "", "now"))

    def test_long_log_preserves_commands_and_hides_webhook(self):
        log = "old line\n" * 10 + "x" * 5000 + "\n```\nhttps://discord.com/api/webhooks/id/secret"
        text = formatter.message("a.service", "*" * 100, "timeout", "1", log, "now")
        self.assertLessEqual(len(text), 1900)
        self.assertNotIn("old line", text)
        self.assertNotIn("/id/secret", text)
        self.assertIn("journalctl --user", text)
        self.assertEqual(text.count("```"), 4)
        self.assertTrue(text.endswith("原因はログで確認してください。"))
        text = formatter.message("a.service", "😀" * 100, "timeout", "1", "😀" * 3000, "now")
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 1900)
        unit = "job@" + "a" * 195 + ".service"
        self.assertIn(f"status {unit} --no-pager", formatter.message(unit, "job", "timeout", "1", "", "now"))

    def test_shell_success_and_failed_delivery(self):
        script = Path(__file__).with_name("notify-failure.sh")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('DISCORD_WEBHOOK_URL="https://discord.invalid/test"\n')
            stubs = {
                "systemctl": '#!/bin/sh\ncase "$5" in\nResult) echo timeout;;\nExecMainStatus) echo 9;;\nDescription) echo 週次棚卸し;;\nesac\n',
                "journalctl": '#!/usr/bin/env python3\nprint("x" * 150000 + "request timed out")\n',
                "curl": '#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\na=sys.argv\nPath(os.environ["CAPTURE"]).write_text(a[a.index("-d")+1])\nPath(a[a.index("-o")+1]).write_text("mock response")\nprint(os.environ["HTTP_CODE"],end="")\n',
            }
            for name, contents in stubs.items():
                path = root / name
                path.write_text(contents)
                path.chmod(0o755)
            env = dict(os.environ, HOME=tmp, PATH=f"{tmp}:{os.environ['PATH']}",
                       CAPTURE=str(root / "payload"))
            for code, expected in (("204", 0), ("403", 1)):
                result = subprocess.run(["sh", str(script), "backlog-enrich.service"],
                                        env=dict(env, HTTP_CODE=code), capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                payload = json.loads((root / "payload").read_text())
                self.assertEqual(payload["allowed_mentions"], {"parse": []})
                self.assertIn("制限時間", payload["content"])
                self.assertIn("週次タスク棚卸し", payload["content"])
                if expected:
                    self.assertIn("HTTP 403", result.stderr)


if __name__ == "__main__":
    unittest.main()
