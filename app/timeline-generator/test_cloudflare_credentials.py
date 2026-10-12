from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from cloudflare_credentials import deployment_environment, read_token


class CredentialTests(unittest.TestCase):
    def test_oauth_selection_does_not_read_file_or_forward_process_token(self):
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "x" * 40}), patch("cloudflare_credentials.read_token") as read:
            env = deployment_environment(use_oauth=True)
            self.assertNotIn("CLOUDFLARE_API_TOKEN", env)
            read.assert_not_called()
            self.assertEqual(deployment_environment()["CLOUDFLARE_API_TOKEN"], "x" * 40)
            read.assert_not_called()

    def test_selected_literal_only_and_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            token = "x" * 40
            path.write_text('OTHER="$(touch should-not-exist)"\nexport CLOUDFLARE_API_TOKEN="' + token + '" # comment\n')
            path.chmod(0o600)
            self.assertEqual(read_token(path), token)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                read_token(path)
            path.chmod(0o600)
            path.write_text("CLOUDFLARE_API_TOKEN=" + token + "\nCLOUDFLARE_API_TOKEN=" + token)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                read_token(path)
            for value in ('"$(touch should-not-exist)"', '"secret', 'x x', ''):
                path.write_text("CLOUDFLARE_API_TOKEN=" + value)
                with self.assertRaisesRegex(ValueError, "Invalid"):
                    read_token(path)
            self.assertFalse((Path(directory) / "should-not-exist").exists())

    def test_missing_assignment_or_file_does_not_load_other_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            self.assertIsNone(read_token(path))
            path.write_text("GEMINI_API_KEY=unrelated\n")
            path.chmod(0o600)
            self.assertIsNone(read_token(path))
