#!/usr/bin/env python3
"""Manually run one opted-in Beads issue and open a GitHub draft PR.

The model runs only through ollama-backlog-draft.py. This host-side program owns
the GitHub credential and refuses to publish unless deterministic gates pass.
There is intentionally no timer or automatic merge path.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/home/ats030")
RESULTS = ROOT / "data/ollama-backlog"
CONFIG = ROOT / "scripts/ollama-backlog-pr.json"
ENV_PATH = ROOT / ".env"
RUNNER = ROOT / "scripts/ollama-backlog-draft.py"
LABEL = "ollama-draft-pr"
# Automatic selection skips an issue after this many failed runs since its last edit.
FAILURE_LIMIT = 3
ISSUE_ID = re.compile(r"^ats030-[a-z0-9]+(?:\.[0-9]+)*$")
GITHUB_HTTPS = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")
GITHUB_SSH = re.compile(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")
ALLOWED_SUFFIXES = {".py", ".js", ".css", ".html", ".go", ".sh"}
MAX_CHANGED_LINES = 80
STATUS_URL = "http://localhost:11434/api/opencode-status"
# 27Bに1000行超のファイルを1回で読ませると300秒では返らない (ats030-hbu8 run2)。
MODEL_TIMEOUT = 1200
# background 枠が埋まっている場合、次の空き枠を待つ最大待機(秒)。
# 1時間 timer の1 tick が無駄にならない程度に抑える。
PROXY_BUSY_WAIT_SECONDS = 300


def command(args: list[str], *, cwd: Path = ROOT, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"})
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                          timeout=timeout, check=False)


def checked(args: list[str], *, cwd: Path = ROOT, timeout: int = 30) -> str:
    result = command(args, cwd=cwd, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def discord_webhook() -> str:
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def notify(title: str, body: str) -> None:
    """Best effort: a notification failure must never change the run's outcome."""
    try:
        webhook = discord_webhook()
    except (OSError, ValueError) as exc:
        print(f"Discord への通知を省略: .env を読めない ({type(exc).__name__})", file=sys.stderr)
        return
    if not webhook:
        print("Discord への通知を省略: DISCORD_WEBHOOK_URL が未設定", file=sys.stderr)
        return
    payload = json.dumps({"content": (f"**{title}**\n```\n{body[:1500]}\n```")[:1900]},
                         ensure_ascii=False).encode()
    try:
        request = urllib.request.Request(webhook, data=payload,
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"webhook returned {response.status}")
    except (RuntimeError, OSError) as exc:
        print(f"Discord への通知に失敗 (http): {exc}", file=sys.stderr)
    except ValueError as exc:
        # The message can echo the webhook URL, which is a secret.
        print(f"Discord への通知に失敗: DISCORD_WEBHOOK_URL の形式が不正 ({type(exc).__name__})", file=sys.stderr)


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if set(config) != {"schema_version", "issues"} or config["schema_version"] != 1:
        raise ValueError("unsupported automation config")
    issues = config["issues"]
    if not isinstance(issues, dict):
        raise ValueError("config issues must be an object")
    for issue_id, entry in issues.items():
        if not ISSUE_ID.fullmatch(issue_id) or not isinstance(entry, dict):
            raise ValueError("invalid issue entry")
        if set(entry) != {"repo", "base", "files", "tests", "read_only"}:
            raise ValueError(f"invalid config fields for {issue_id}")
        if not isinstance(entry["repo"], str) or not re.fullmatch(r"app/[a-z0-9-]+", entry["repo"]):
            raise ValueError(f"invalid repository for {issue_id}")
        if entry["base"] not in ("main", "master"):
            raise ValueError(f"invalid base branch for {issue_id}")
        for field, limit in (("files", 3), ("tests", 2), ("read_only", 30)):
            values = entry[field]
            if not isinstance(values, list) or len(values) > limit or any(
                    not isinstance(value, str) or not value for value in values):
                raise ValueError(f"invalid {field} for {issue_id}")
        if not entry["files"] or not entry["tests"] or len(set(entry["files"])) != len(entry["files"]):
            raise ValueError(f"files and tests are required for {issue_id}")
        for name in entry["files"]:
            relative = Path(name)
            if (relative.is_absolute() or name != relative.as_posix()
                    or any(part.startswith(".") for part in relative.parts)
                    or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
                    or relative.suffix not in ALLOWED_SUFFIXES
                    or "tests" in relative.parts or relative.name in ("test.py", "conftest.py")
                    or relative.name.startswith("test_")
                    or relative.name.endswith(("_test.go", ".test.js", ".spec.js"))):
                raise ValueError(f"unsafe file name for {issue_id}: {name}")
    return issues


def ready_issues() -> list[dict]:
    rows = json.loads(checked(["bd", "ready", "--json", "--limit", "0"]))
    if not isinstance(rows, list):
        raise RuntimeError("bd ready returned an unexpected format")
    return rows


def eligible(issue: dict, config: dict) -> bool:
    labels = set(issue.get("labels") or ())
    return (issue.get("id") in config and issue.get("status") == "open"
            and not issue.get("assignee") and bool(issue.get("acceptance_criteria"))
            and LABEL in labels and not labels & {"human", "decision", "human-action"})


def failed_runs(issue: dict) -> int:
    """Count failed generation runs started after the issue was last updated.

    Editing the issue (e.g. sharpening its acceptance criteria) resets the count.
    Busy retries and runs without a report do not count.
    """
    try:
        since = datetime.fromisoformat(issue.get("updated_at", "").replace("Z", "+00:00"))
    except ValueError:
        since = datetime.min.replace(tzinfo=timezone.utc)
    count = 0
    for run_dir in RESULTS.glob(f"{issue['id']}-*"):
        stamp = run_dir.name[len(issue["id"]) + 1:]
        if not re.fullmatch(r"\d{8}T\d{6}Z", stamp):
            continue
        started = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if started < since:
            continue
        try:
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if report.get("status") != "ready_for_review" and not report.get("retryable_busy"):
            count += 1
    return count


def select_issue(rows: list[dict], config: dict, requested: str | None) -> dict | None:
    candidates = sorted((row for row in rows if eligible(row, config)
                         and (requested or failed_runs(row) < FAILURE_LIMIT)),
                        key=lambda row: (row.get("priority", 4), row.get("created_at", ""), row["id"]))
    if requested:
        return next((row for row in candidates if row["id"] == requested), None)
    return candidates[0] if candidates else None


def proxy_background_free() -> int:
    """Return how many background generation slots are currently free.

    The draft runner is classified as ``background`` via
    ``X-Client-App: backlog-draft`` (see ollama-backlog-draft.py), so a
    foreground/opencode interaction can no longer preempt it. The old
    ``state == idle AND queue_depth == 0`` check caused hourly busy because
    OpenCode always holds the interactive slot on a busy host.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(STATUS_URL, timeout=3) as response:
        if response.headers.get_content_type() != "application/json":
            raise RuntimeError("Ollama proxy status endpoint is unavailable")
        status = json.loads(response.read(4096))
    if not isinstance(status, dict) or status.get("state") not in ("idle", "queued", "generating"):
        raise RuntimeError("Ollama proxy returned invalid status")
    free = status.get("background_free")
    if not isinstance(free, int) or free < 0:
        raise RuntimeError("Ollama proxy did not report background_free")
    return free


def github_repository(repo: Path) -> str:
    url = checked(["git", "remote", "get-url", "origin"], cwd=repo)
    match = GITHUB_HTTPS.fullmatch(url) or GITHUB_SSH.fullmatch(url)
    if not match:
        raise RuntimeError("origin must be a GitHub repository without embedded credentials")
    return f"{match.group(1)}/{match.group(2)}"


def remote_head(repo: Path, branch: str) -> str:
    result = checked(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"],
                     cwd=repo, timeout=30)
    return result.split("\t", 1)[0] if result else ""


def no_existing_pr(repo: Path, github: str, branch: str) -> bool:
    rows = json.loads(checked(["gh", "pr", "list", "--repo", github, "--head", branch,
                               "--state", "all", "--json", "number,url", "--limit", "100"],
                              cwd=repo, timeout=30))
    return isinstance(rows, list) and not rows


def claim_issue(issue_id: str) -> None:
    rows = json.loads(checked(["bd", "update", issue_id, "--claim", "--actor",
                               "ollama-backlog", "--json"]))
    if (len(rows) != 1 or rows[0].get("status") != "in_progress"
            or rows[0].get("assignee") != "ollama-backlog"):
        raise RuntimeError("Beads did not assign the issue to ollama-backlog")


def release_issue(issue_id: str) -> None:
    checked(["bd", "update", issue_id, "--status", "open", "--assignee", "",
             "--actor", "ollama-backlog", "--json"])


def validate_draft(report: dict, entry: dict, repo: Path, issue_id: str) -> Path:
    if (report.get("issue_id") != issue_id or report.get("source_repository") != str(repo)
            or report.get("status") != "ready_for_review" or report.get("success") is not True
            or report.get("model_exit_code") != 0 or report.get("mode") != "one_pass"
            or report.get("offline_tests") is not True
            or report.get("allowed_files") != entry["files"]
            or report.get("tests_skipped") is not False
            or report.get("untracked_files") or report.get("support_unchanged") is not True):
        raise RuntimeError("draft report does not satisfy publication gates")
    if [test.get("command") for test in report.get("tests", [])] != entry["tests"] or any(
            test.get("exit_code") != 0 for test in report["tests"]):
        raise RuntimeError("fixed tests did not pass")
    worktree = Path(report["worktree"])
    if (not worktree.resolve().is_relative_to(RESULTS.resolve())
            or worktree.name != "worktree" or not worktree.is_dir()):
        raise RuntimeError("worktree path is outside the result area")
    names = checked(["git", "diff", "--name-only", "-z"], cwd=worktree)
    changed = set(names.rstrip("\0").split("\0")) if names else set()
    if not changed or not changed <= set(entry["files"]):
        raise RuntimeError("draft changed a non-allowlisted file")
    if checked(["git", "diff", "--summary"], cwd=worktree):
        raise RuntimeError("draft changed file modes or symlinks")
    status = checked(["git", "diff", "--name-status", "--no-renames"], cwd=worktree)
    if any(not row.startswith("M\t") for row in status.splitlines()):
        raise RuntimeError("draft added, deleted, or renamed a file")
    if checked(["git", "diff", "--cached", "--name-only"], cwd=worktree):
        raise RuntimeError("draft contains staged changes")
    for name in changed:
        path = worktree / name
        if path.resolve() != path or not path.is_file():
            raise RuntimeError("draft contains a symlink or non-file")
    numstat = checked(["git", "diff", "--numstat"], cwd=worktree)
    lines = 0
    for row in numstat.splitlines():
        added, removed, _ = row.split("\t", 2)
        if not added.isdecimal() or not removed.isdecimal():
            raise RuntimeError("binary diffs are not allowed")
        lines += int(added) + int(removed)
    if lines > MAX_CHANGED_LINES:
        raise RuntimeError("draft exceeds the changed-line limit")
    checked(["git", "diff", "--check"], cwd=worktree)
    if checked(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree):
        raise RuntimeError("draft contains untracked files")
    return worktree


def publish(issue: dict, entry: dict, repo: Path, worktree: Path, report: dict,
            github: str, branch: str) -> str:
    base = entry["base"]
    source_head = report["source_head"]
    if (checked(["git", "rev-parse", "HEAD"], cwd=repo) != source_head
            or remote_head(repo, base) != source_head or remote_head(repo, branch)):
        raise RuntimeError("repository changed or draft branch already exists")
    if checked(["git", "status", "--porcelain"], cwd=repo):
        raise RuntimeError("source repository changed during generation")
    if not no_existing_pr(repo, github, branch):
        raise RuntimeError("an issue PR already exists")
    checked(["git", "switch", "-c", branch], cwd=worktree)
    checked(["git", "add", "--", *entry["files"]], cwd=worktree)
    checked(["git", "diff", "--cached", "--check"], cwd=worktree)
    checked(["git", "-c", "core.hooksPath=/dev/null", "commit", "-m",
             f"Draft Ollama fix for {issue['id']}"], cwd=worktree, timeout=60)
    checked(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], cwd=worktree, timeout=90)
    body = (f"Beads issue: {issue['id']}\n\n"
            "Ollama generated this draft in an isolated worktree. Human review is required before merge.\n\n"
            f"Source commit: `{source_head}`\n"
            f"Allowed files: {', '.join(entry['files'])}\n"
            "Fixed checks:\n" + "".join(f"- `{test}`\n" for test in entry["tests"]))
    body_path = Path(report["run_dir"]) / "draft-pr-body.md"
    body_path.write_text(body, encoding="utf-8")
    url = checked(["gh", "pr", "create", "--repo", github, "--draft", "--base", base,
                   "--head", branch, "--title", f"[Ollama draft] {issue['title']}",
                   "--body-file", str(body_path)], cwd=repo, timeout=90)
    if not url.startswith(f"https://github.com/{github}/pull/"):
        raise RuntimeError("GitHub returned an unexpected PR URL")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--issue", help="select this opted-in issue")
    parser.add_argument("--run", action="store_true", help="generate and publish one draft PR")
    args = parser.parse_args()
    config = load_config(args.config)
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "automation.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another Ollama backlog run is active") from None
        issue = select_issue(ready_issues(), config, args.issue)
        if not issue:
            print(json.dumps({"status": "no_eligible_issue", "requested": args.issue}, ensure_ascii=False))
            return 0 if not args.issue else 2
        entry = config[issue["id"]]
        repo = (ROOT / entry["repo"]).resolve()
        if repo.parent != ROOT / "app":
            raise RuntimeError("only independent app repositories are supported")
        github = github_repository(repo)
        branch = f"ollama/{issue['id']}"
        if remote_head(repo, branch) or not no_existing_pr(repo, github, branch):
            print(json.dumps({"status": "already_attempted", "issue_id": issue["id"]}))
            return 0
        if not args.run:
            print(json.dumps({"status": "eligible", "issue_id": issue["id"],
                              "repo": entry["repo"], "github": github}, ensure_ascii=False))
            return 0
        try:
            free = proxy_background_free()
            waited = 0
        except (urllib.error.URLError, ValueError, RuntimeError) as exc:
            print(json.dumps({"status": "busy_unknown", "reason": str(exc)}, ensure_ascii=False))
            return 75
        if not free:
            deadline = time.monotonic() + PROXY_BUSY_WAIT_SECONDS
            waited = PROXY_BUSY_WAIT_SECONDS
            while time.monotonic() < deadline:
                time.sleep(min(30, max(1, deadline - time.monotonic())))
                try:
                    free = proxy_background_free()
                except (urllib.error.URLError, ValueError, RuntimeError) as exc:
                    print(json.dumps({"status": "busy_unknown", "reason": str(exc)},
                                     ensure_ascii=False))
                    return 75
                if free:
                    break
        if not free:
            print(json.dumps({"status": "busy", "issue_id": issue["id"],
                              "waited_seconds": waited}, ensure_ascii=False))
            return 75
        source_head = checked(["git", "rev-parse", "HEAD"], cwd=repo)
        if checked(["git", "status", "--porcelain"], cwd=repo):
            raise RuntimeError("source repository is not clean")
        if checked(["git", "branch", "--show-current"], cwd=repo) != entry["base"]:
            raise RuntimeError("source repository is not on the configured base branch")
        if remote_head(repo, entry["base"]) != source_head:
            raise RuntimeError("source branch is not up to date with origin")
        cmd = [sys.executable, str(RUNNER), issue["id"], "--repo", entry["repo"],
               "--model-timeout", str(MODEL_TIMEOUT), "--offline-tests"]
        for name in entry["files"]:
            cmd += ["--one-pass-file", name, "--allowed-file", name]
        for test in entry["tests"]:
            cmd += ["--test", test]
        for name in entry["read_only"]:
            cmd += ["--read-only", name]
        result = command(cmd, timeout=MODEL_TIMEOUT + 660)
        try:
            outcome = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"draft runner failed: {result.stderr.strip()[:300]}") from None
        run_dir = Path(outcome["run_dir"])
        if run_dir.resolve().parent != RESULTS.resolve():
            raise RuntimeError("draft runner returned an unexpected run directory")
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        if result.returncode or report.get("status") != "ready_for_review":
            status = report.get("status", "failed")
            print(json.dumps({"status": status, "issue_id": issue["id"],
                              "run_dir": str(run_dir)}, ensure_ascii=False))
            if not report.get("retryable_busy"):
                notify("Ollama backlog failed (generation)",
                       f"issue={issue['id']} status={status} run={run_dir}")
            return 75 if report.get("retryable_busy") else 1
        worktree = validate_draft(report, entry, repo, issue["id"])
        if report["source_head"] != source_head:
            raise RuntimeError("draft source commit changed")
        latest = json.loads(checked(["bd", "show", issue["id"], "--json"]))
        still_ready = any(row.get("id") == issue["id"] for row in ready_issues())
        if len(latest) != 1 or not eligible(latest[0], config) or not still_ready:
            raise RuntimeError("issue eligibility changed during generation")
        claim_issue(issue["id"])
        try:
            url = publish(issue, entry, repo, worktree, report, github, branch)
        except Exception as exc:
            if not remote_head(repo, branch):
                release_issue(issue["id"])
            notify("Ollama backlog failed (publish)", f"issue={issue['id']} error={exc}")
            exc.notified = True
            raise
        (run_dir / "draft-pr-url.txt").write_text(url + "\n", encoding="utf-8")
        try:
            checked(["bd", "comment", issue["id"], f"Ollama draft PR: {url}; run: {run_dir}",
                     "--actor", "ollama-backlog", "--json"])
        except RuntimeError as exc:
            print(json.dumps({"status": "draft_pr_created_beads_comment_failed",
                              "issue_id": issue["id"], "url": url, "run_dir": str(run_dir),
                              "warning": str(exc)}, ensure_ascii=False))
            notify("Ollama backlog warning", f"issue={issue['id']} PR created but Beads comment failed: {exc}")
            return 1
        print(json.dumps({"status": "draft_pr_created", "issue_id": issue["id"],
                          "url": url, "run_dir": str(run_dir)}, ensure_ascii=False))
        notify("Ollama draft PR created", f"issue={issue['id']}\n{url}")
        return 0


def run() -> int:
    try:
        return main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
            urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        if not getattr(exc, "notified", False):
            notify("Ollama backlog failed", f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(run())
