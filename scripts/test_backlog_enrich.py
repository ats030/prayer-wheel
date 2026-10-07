"""Offline contract tests for the weekly Ollama backlog enrichment report."""

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from os import environ
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "backlog_enrich", HERE / "backlog-enrich.py")
enrich = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enrich)
CAND = enrich.candidates  # enrich 内部のcandidatesコピーをパッチ対象にする

NOW = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)
GOOD_GATES = {"independent": True, "github": True, "clean": True,
              "base_branch": "main", "has_tests": True}
BAD_GATES = {"independent": True, "github": True, "clean": False,
             "base_branch": None, "has_tests": False}


ENRICH_CANDIDATES = enrich.candidates  # enrich 内部のcandidatesコピーをパッチ対象にする


def issue(id, title="t", acceptance="done", status="open", age_days=1,
          priority=1, labels=None, assignee=None, repo_text="dummy-app"):
    created = NOW - timedelta(days=age_days + 1)
    updated = (NOW - timedelta(days=age_days) if age_days > 0
               else NOW - timedelta(hours=3))
    row = {
        "id": id, "title": title, "description": f"{repo_text} work: 設定項目を検証できる",
        "status": status, "priority": priority, "labels": labels or [],
        "acceptance_criteria": acceptance, "design": "",
        "created_at": created.isoformat(), "updated_at": updated.isoformat(),
        "started_at": None,
    }
    if assignee:
        row["assignee"] = assignee
    return row


def fake_bd(directory: Path, issues: list[dict]):
    """A bd stub that logs every invocation and answers `ready --json`."""
    bin_dir = directory / "bin"
    bin_dir.mkdir()
    fixture = {"issues": issues}
    (directory / "bd-fixture.json").write_text(json.dumps(fixture), encoding="utf-8")
    script = bin_dir / "bd"
    script.write_text(
        "#!/bin/sh\n"
        'LOG="$(dirname "$0")/../bd-args.log"\n'
        "printf '%s\\n' \"$*\" >> \"$LOG\"\n"
        "if [ \"$1\" = \"ready\" ]; then\n"
        '  cat "$(dirname "$0")/../bd-fixture.json" | python3 -c '
        '"import json,sys; print(json.dumps(json.load(sys.stdin)[\\"issues\\"]))"\n'
        "  exit 0\n"
        "fi\n"
        "echo \"bd stub: refusing $*\" >&2\n"
        "exit 2\n", encoding="utf-8")
    script.chmod(0o755)
    return bin_dir


class NotifyTests(unittest.TestCase):
    def test_webhook_request_and_http_failure(self):
        from urllib.error import HTTPError
        from unittest.mock import MagicMock

        response = MagicMock()
        response.__enter__.return_value.status = 204
        with patch.object(enrich, "webhook_url", return_value="https://discord.invalid/test"), \
             patch.object(enrich.urllib.request, "urlopen", return_value=response) as send, \
             redirect_stdout(io.StringIO()) as output:
            enrich.notify("weekly", "report")
        request = send.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "backlog-enrich/1.0")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data)["content"], "**weekly**\nreport")
        self.assertEqual(json.loads(request.data)["allowed_mentions"], {"parse": []})
        self.assertEqual(send.call_args.kwargs["timeout"], 5)
        self.assertIn("HTTP 204", output.getvalue())

        error = HTTPError("https://discord.invalid/test", 403, "Forbidden", {}, None)
        with patch.object(enrich, "webhook_url", return_value="https://discord.invalid/test"), \
             patch.object(enrich.urllib.request, "urlopen", side_effect=error), \
             patch.object(enrich.sys, "stderr", io.StringIO()) as errors:
            enrich.notify("weekly", "report")
        self.assertIn("403", errors.getvalue())
        self.assertNotIn("discord.invalid", errors.getvalue())


class StaleTests(unittest.TestCase):
    def test_stale_requires_sixteen_plus_days_idle(self):
        rows = enrich.stale_candidates([
            issue("ats030-a", age_days=20, status="open"),
            issue("ats030-b", age_days=20, status="in_progress"),
            issue("ats030-c", age_days=3, status="open"),
            issue("ats030-d", age_days=30, status="closed"),
        ], now=NOW)
        self.assertEqual([r["id"] for r in rows], ["ats030-a", "ats030-b"])
        self.assertEqual(rows[0]["idle_days"], 20)
        self.assertIn("bd defer ats030-a", rows[0]["proposal"])
        self.assertIn("自動実行しない", rows[0]["proposal"])

    def test_in_progress_activity_counts_as_fresh(self):
        fresh = issue("ats030-x", age_days=2)
        # in_progress with a started_at today is not stale even if updated older.
        fresh["started_at"] = (NOW - timedelta(hours=2)).isoformat()
        stale = enrich.stale_candidates([fresh], now=NOW)
        self.assertEqual(stale, [])


class DraftTestCaseTests(unittest.TestCase):
    def test_draft_is_single_and_grounded_in_description(self):
        row = enrich.draft_acceptance(issue(
            "ats030-d", acceptance="",
            title="dummy-app: 設定項目を検証できる"))
        self.assertIn("設定項目を検証できる", row)
        self.assertIn("検証が通ること", row)
        self.assertNotIn("bd", row)
        self.assertNotIn("github", row.lower().replace("dummy-app: ", ""))

    def test_draft_falls_back_to_title_when_description_empty(self):
        bad = issue("ats030-e", acceptance="")
        bad["description"] = ""
        row = enrich.draft_acceptance(bad)
        self.assertEqual(row.count("・"), 1)
        self.assertTrue(row.endswith("検証が通ること"))


class ReportTests(unittest.TestCase):
    def test_notification_explains_counts_and_handles_long_titles(self):
        rows = [{"id": f"ats030-{i}", "title": "長いタスク名*" * 100,
                 "idle_days": 30} for i in range(8)]
        report = {"summary": {"stale": 8, "missing_acceptance": 8,
                              "ready": 8, "parked": 8, "skipped": 0},
                  "stale_candidates": rows, "missing_acceptance": rows,
                  "candidates": {"ready": rows, "parked": rows, "skipped": []}}
        body = enrich.notification_body(report)
        self.assertIn("14日以上動きなし：8件", body)
        self.assertIn("全残タスクの集計ではありません", body)
        self.assertIn("重複", body)
        self.assertIn("完了条件なし", body)
        self.assertEqual(body.count("ほか5件"), 3)
        self.assertIn("タスクの更新・延期・完了処理は行っていません", body)
        self.assertLess(len(body) + len("**今週のタスク棚卸し｜2026-10-07**\n"), 1900)
        self.assertIn("\\*", body)
        report["missing_acceptance"] = [rows[0], rows[0]]
        body = enrich.notification_body(report)
        self.assertIn("完了条件の記載なし：1件", body)
        self.assertEqual(body.split("**完了条件なし")[1].split("**自動PR候補")[0].count("ats030-0"), 1)

    def test_empty_notification_has_no_task_sections(self):
        report = {"summary": dict.fromkeys(
            ["stale", "missing_acceptance", "ready", "parked", "skipped"], 0),
                  "stale_candidates": [], "missing_acceptance": [],
                  "candidates": {"ready": []}}
        body = enrich.notification_body(report)
        self.assertIn("14日以上動きなし：0件", body)
        self.assertNotIn("**長期未更新", body)
        self.assertIn("http://ubuntu-server-app.tailf74832.ts.net:8509/", body)

    def test_report_reuses_candidate_ranking_and_states(self):
        issues = [
            issue("ats030-ready1", acceptance="done"),
            issue("ats030-need", acceptance=""),
            issue("ats030-lb", acceptance="done", labels=["ollama-draft-pr"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps(
                {"schema_version": 1, "issues": {"ats030-ready1": {}}}))
            with patch.object(enrich, "CONFIG", config), \
                 patch.object(CAND, "repositories",
                              return_value=[("dummy-app", issues)]), \
                 patch.object(CAND, "gates", return_value=GOOD_GATES), \
                 patch.object(CAND, "score", return_value=42):
                report = enrich.build_report(issues, now=NOW)
        self.assertEqual(report["candidates"]["ready"], [])
        states = {r["id"]: r["state"] for r in report["candidates"]["parked"] +
                  report["candidates"]["skipped"]}
        self.assertEqual(states["ats030-need"], "needs_acceptance")
        self.assertEqual(states["ats030-lb"], "labeled_not_configured")
        self.assertIn("ats030-ready1",
                      {r["id"] for r in report["candidates"]["skipped"]
                       if r["state"] == "already_configured"})
        self.assertEqual(report["summary"]["stale"], 0)

    def test_ready_issue_is_ranked_with_score(self):
        issues = [issue("ats030-r", acceptance="done")]
        with patch.object(CAND, "repositories",
                          return_value=[("dummy-app", issues)]), \
             patch.object(CAND, "gates", return_value=GOOD_GATES):
            report = enrich.build_report(issues, now=NOW)
        self.assertEqual(len(report["candidates"]["ready"]), 1)
        self.assertGreater(report["candidates"]["ready"][0]["score"], 0)
        self.assertEqual(report["candidates"]["ready"][0]["gates"], GOOD_GATES)
        # 欠落草案は needs_acceptance 領域にしか出ない。
        self.assertEqual(report["missing_acceptance"], [])

    def test_ready_issue_with_failed_gates_is_parked(self):
        issues = [issue("ats030-p", acceptance="done")]
        with patch.object(CAND, "repositories",
                          return_value=[("dummy-app", issues)]), \
             patch.object(CAND, "gates", return_value=BAD_GATES):
            report = enrich.build_report(issues, now=NOW)
        self.assertEqual(report["candidates"]["parked"][0]["state"], "repo_gates_fail")


class MainTests(unittest.TestCase):
    def test_main_writes_report_and_never_mutates_beads(self):
        fixture_issues = [
            issue("ats030-stale1", age_days=30),
            issue("ats030-need1", acceptance="", age_days=1),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = fake_bd(root, fixture_issues)
            (root / "pr.json").write_text(json.dumps(
                {"schema_version": 1, "issues": {}}))
            results = root / "data/ollama-backlog"
            results.mkdir(parents=True)
            with patch.object(CAND, "ROOT", root), \
                 patch.object(CAND, "repositories",
                              return_value=[("dummy-app", fixture_issues)]), \
                 patch.object(CAND, "gates", return_value=GOOD_GATES), \
                 patch.object(enrich, "ROOT", root), \
                 patch.object(enrich, "CONFIG", root / "pr.json"), \
                 patch.object(enrich, "ENV_PATH", root / "no-env"), \
                 patch.object(enrich, "RESULTS_DIR", results), \
                 patch.dict(environ, {"PATH": f"{bin_dir}:{environ['PATH']}"}):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = enrich.main()
            printed = buffer.getvalue()
            self.assertEqual(code, 0)
            report_files = list(results.glob("enrich-*.json"))
            self.assertEqual(len(report_files), 1)
            report = json.loads(report_files[0].read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["stale"], 1)
            self.assertEqual(report["summary"]["missing_acceptance"], 1)
            self.assertEqual(report["stale_candidates"][0]["id"], "ats030-stale1")
            self.assertIn("bd defer ats030-stale1",
                          report["stale_candidates"][0]["proposal"])
            # 安全線: bd は `ready` (read) しか呼べない。
            args_log = (root / "bd-args.log").read_text(encoding="utf-8").splitlines()
            self.assertTrue(all("ready" in line for line in args_log), args_log)
            self.assertNotIn("defer", " ".join(args_log))
            self.assertNotIn("update", " ".join(args_log))
            self.assertIn("stale=1", printed)
            self.assertIn("report:", printed)


if __name__ == "__main__":
    unittest.main()
