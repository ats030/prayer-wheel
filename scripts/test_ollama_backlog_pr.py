"""Offline contract tests for the manual Ollama draft PR workflow."""

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "ollama_backlog_pr", Path(__file__).with_name("ollama-backlog-pr.py"))
pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr)
RUNNER_SPEC = importlib.util.spec_from_file_location(
    "ollama_backlog_draft", Path(__file__).with_name("ollama-backlog-draft.py"))
draft = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(draft)


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True,
                          check=True).stdout.strip()


class SelectionTests(unittest.TestCase):
    def test_opt_in_requires_open_unassigned_ready_issue_with_acceptance(self):
        config = {"ats030-good": {}, "ats030-human": {}, "ats030-claimed": {}}
        rows = [
            {"id": "ats030-human", "status": "open", "labels": [pr.LABEL, "human"],
             "acceptance_criteria": "done", "priority": 1},
            {"id": "ats030-claimed", "status": "open", "labels": [pr.LABEL],
             "assignee": "another-agent", "acceptance_criteria": "done", "priority": 1},
            {"id": "ats030-good", "status": "open", "labels": [pr.LABEL],
             "acceptance_criteria": "done", "priority": 3},
        ]
        self.assertEqual(pr.select_issue(rows, config, None)["id"], "ats030-good")
        self.assertIsNone(pr.select_issue(rows, config, "ats030-human"))
        self.assertFalse(pr.eligible({"id": "ats030-good", "status": "open",
                                      "labels": [pr.LABEL]}, config))

    def test_config_rejects_unsafe_or_oversized_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            entry = {"repo": "app/app-portal", "base": "main", "files": ["icons.py"],
                     "tests": ["python -m pytest -q test_icons.py"], "read_only": []}
            path.write_text(json.dumps({"schema_version": 1,
                                        "issues": {"ats030-test": entry}}))
            self.assertEqual(pr.load_config(path)["ats030-test"], entry)
            entry["files"] = ["../.ssh/id_rsa"]
            path.write_text(json.dumps({"schema_version": 1,
                                        "issues": {"ats030-test": entry}}))
            with self.assertRaises(ValueError):
                pr.load_config(path)
            entry["files"] = ["tests/test_icons.py"]
            path.write_text(json.dumps({"schema_version": 1,
                                        "issues": {"ats030-test": entry}}))
            with self.assertRaises(ValueError):
                pr.load_config(path)

    def test_offline_test_sandbox_unshares_network(self):
        args = draft.sandbox(Path("/tmp/worktree"), Path("/tmp/agent-home"), [],
                             Path("/home/ats030/app/example"), offline=True)
        self.assertIn("--unshare-net", args)
        self.assertNotIn("--unshare-net", draft.sandbox(
            Path("/tmp/worktree"), Path("/tmp/agent-home"), [],
            Path("/home/ats030/app/example")))

    def test_proxy_status_must_be_json_and_idle(self):
        class Opener:
            def __init__(self, state, content_type="application/json"):
                self.state = state
                self.content_type = content_type

            def open(self, _url, timeout):
                self.assert_timeout = timeout
                response = io.BytesIO(json.dumps(self.state).encode())
                response.headers = Message()
                response.headers["Content-Type"] = self.content_type
                return response

        idle = {"state": "idle", "queue_depth": 0, "active_count": 0}
        with patch.object(pr.urllib.request, "build_opener", return_value=Opener(idle)):
            self.assertTrue(pr.proxy_idle())
        with patch.object(pr.urllib.request, "build_opener", return_value=Opener(
                {**idle, "active_count": 1})):
            self.assertFalse(pr.proxy_idle())
        with patch.object(pr.urllib.request, "build_opener", return_value=Opener(
                idle, "text/html")):
            with self.assertRaises(RuntimeError):
                pr.proxy_idle()

    def test_existing_pr_blocks_second_attempt(self):
        with patch.object(pr, "checked", return_value='[{"number":7,"url":"https://github.com/x/y/pull/7"}]'):
            self.assertFalse(pr.no_existing_pr(Path("/tmp/repo"), "x/y", "ollama/ats030-a"))

    def test_busy_does_not_run_model(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(json.dumps({"schema_version": 1, "issues": {
                "ats030-good": {"repo": "app/app-portal", "base": "main",
                                "files": ["icons.py"], "tests": ["python -m pytest -q test_icons.py"],
                                "read_only": []}}}))
            row = {"id": "ats030-good", "status": "open", "labels": [pr.LABEL],
                   "acceptance_criteria": "done"}
            with (patch.object(pr, "RESULTS", Path(directory)),
                  patch.object(pr, "ready_issues", return_value=[row]),
                  patch.object(pr, "github_repository", return_value="owner/repo"),
                  patch.object(pr, "remote_head", return_value=""),
                  patch.object(pr, "no_existing_pr", return_value=True),
                  patch.object(pr, "proxy_idle", return_value=False),
                  patch.object(pr, "command", side_effect=AssertionError("model must not run")),
                  patch("sys.argv", ["pr", "--config", str(config_path), "--run"])):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(pr.main(), 75)
                self.assertEqual(json.loads(output.getvalue())["status"], "busy")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bare = self.root / "origin.git"
        self.repo = self.root / "repo"
        self.results = self.root / "results"
        self.results.mkdir()
        self.run_dir = self.results / "ats030-test-run"
        self.run_dir.mkdir()
        self.worktree = self.run_dir / "worktree"
        git("init", "-q", "--bare", str(self.bare))
        git("init", "-q", "-b", "main", str(self.repo))
        git("config", "user.name", "Test", cwd=self.repo)
        git("config", "user.email", "test@example.invalid", cwd=self.repo)
        (self.repo / "fix.py").write_text("old\n")
        (self.repo / "other.py").write_text("base\n")
        git("add", "fix.py", "other.py", cwd=self.repo)
        git("commit", "-qm", "base", cwd=self.repo)
        git("remote", "add", "origin", str(self.bare), cwd=self.repo)
        git("push", "-q", "origin", "main", cwd=self.repo)
        git("worktree", "add", "-q", "--detach", str(self.worktree), "HEAD", cwd=self.repo)
        (self.worktree / "fix.py").write_text("new\n")
        self.source_head = git("rev-parse", "HEAD", cwd=self.repo)
        self.entry = {"repo": "app/repo", "base": "main", "files": ["fix.py"],
                      "tests": ["python -m pytest -q test_fix.py"], "read_only": []}
        self.report = {"issue_id": "ats030-test", "source_repository": str(self.repo),
                       "source_head": self.source_head, "status": "ready_for_review",
                       "success": True, "model_exit_code": 0, "mode": "one_pass",
                       "offline_tests": True, "allowed_files": ["fix.py"],
                       "tests_skipped": False,
                       "untracked_files": [], "support_unchanged": True,
                       "tests": [{"command": self.entry["tests"][0], "exit_code": 0}],
                       "worktree": str(self.worktree), "run_dir": str(self.run_dir)}

    def test_validate_draft_rejects_other_file(self):
        with patch.object(pr, "RESULTS", self.results):
            self.assertEqual(pr.validate_draft(self.report, self.entry, self.repo,
                                               "ats030-test"), self.worktree)
            (self.worktree / "other.py").write_text("changed\n")
            with self.assertRaisesRegex(RuntimeError, "non-allowlisted"):
                pr.validate_draft(self.report, self.entry, self.repo, "ats030-test")

    def test_publish_pushes_only_issue_branch_and_asks_for_draft_pr(self):
        calls = []
        real_checked = pr.checked

        def checked(args, **kwargs):
            if args[:3] == ["gh", "pr", "create"]:
                calls.append(args)
                return "https://github.com/owner/repo/pull/1"
            return real_checked(args, **kwargs)

        with patch.object(pr, "checked", side_effect=checked), patch.object(
                pr, "no_existing_pr", return_value=True):
            url = pr.publish({"id": "ats030-test", "title": "Fix"}, self.entry,
                             self.repo, self.worktree, self.report,
                             "owner/repo", "ollama/ats030-test")
        self.assertEqual(url, "https://github.com/owner/repo/pull/1")
        self.assertEqual(git("--git-dir", str(self.bare), "rev-parse", "refs/heads/main"),
                         self.source_head)
        self.assertNotEqual(git("--git-dir", str(self.bare), "rev-parse",
                                "refs/heads/ollama/ats030-test"), self.source_head)
        self.assertIn("--draft", calls[0])
        self.assertIn("--body-file", calls[0])


if __name__ == "__main__":
    unittest.main()
