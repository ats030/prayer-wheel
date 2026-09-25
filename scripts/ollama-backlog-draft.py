#!/usr/bin/env python3
"""Run one Beads issue with local OpenCode and keep only a reviewable draft.

The model can edit an isolated Git worktree. It cannot invoke a shell, see the
normal home directory, or write to the source repository. Tests run separately
inside the same restricted filesystem view. No issue state is changed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/home/ats030")
RESULTS = ROOT / "data/ollama-backlog"
OPENCODE = ROOT / ".opencode/bin/opencode"
VENV = ROOT / ".venv"
ISSUE_ID = re.compile(r"^ats030-[a-z0-9]+$")


def command(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)


def issue_record(issue_id: str) -> dict:
    result = command(["bd", "show", issue_id, "--json"], cwd=ROOT)
    if result.returncode:
        raise RuntimeError(f"bd show failed: {result.stderr.strip()[:300]}")
    rows = json.loads(result.stdout)
    if len(rows) != 1 or rows[0]["id"] != issue_id:
        raise RuntimeError("bd returned an unexpected issue")
    issue = rows[0]
    if issue.get("status") != "open" or set(issue.get("labels") or ()) & {"human", "decision"}:
        raise RuntimeError("pilot accepts only open, agent-owned issues")
    if not issue.get("acceptance_criteria"):
        raise RuntimeError("issue needs acceptance criteria before a draft run")
    return issue


def repository(path: str) -> Path:
    repo = (ROOT / path).resolve()
    if not repo.is_relative_to(ROOT) or not repo.is_dir():
        raise RuntimeError("repository must be a directory under the workspace")
    if repo.parent != ROOT / "app":
        raise RuntimeError("this pilot supports app/<repository> only")
    top = command(["git", "rev-parse", "--show-toplevel"], cwd=repo)
    if top.returncode or Path(top.stdout.strip()).resolve() != repo:
        raise RuntimeError("--repo must point to the root of a Git repository")
    status = command(["git", "status", "--porcelain"], cwd=repo)
    if status.returncode or status.stdout.strip():
        raise RuntimeError("source repository must be clean")
    return repo


def sandbox(worktree: Path, state: Path, support: list[Path], repo: Path) -> list[str]:
    # The host home, Git metadata, credentials, systemd socket, and bd executable
    # are absent. Network remains shared solely to reach the existing Ollama proxy.
    args = ["bwrap", "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc",
            "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--dir", "/opt", "--dir", "/home",
            "--dir", "/home/ats030", "--dir", "/home/ats030/app",
            "--ro-bind", str(OPENCODE), "/opt/opencode", "--ro-bind", str(VENV), str(VENV),
            "--bind", str(state), "/home/agent", "--bind", str(worktree), str(repo),
            "--ro-bind", str(state.parent / "opencode.json"), "/opt/opencode.json"]
    ripgrep = shutil.which("rg")
    if ripgrep:
        args += ["--ro-bind", str(Path(ripgrep).resolve()), "/opt/rg"]
    for system_file in ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf"):
        if Path(system_file).exists():
            args += ["--ro-bind", system_file, system_file]
    if Path("/etc/ssl/certs").exists():
        args += ["--dir", "/etc/ssl", "--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs"]
    for source in support:
        relative = source.relative_to(ROOT)
        parent = Path("/home/ats030") / relative.parent
        for part in reversed(list(parent.parents)):
            if str(part) not in ("/", "/home"):
                args += ["--dir", str(part)]
        args += ["--dir", str(parent), "--ro-bind", str(source), str(Path("/home/ats030") / relative)]
    args += ["--clearenv", "--setenv", "HOME", "/home/agent",
             "--setenv", "XDG_CONFIG_HOME", "/home/agent/.config",
             "--setenv", "XDG_CACHE_HOME", "/home/agent/.cache",
             "--setenv", "XDG_DATA_HOME", "/home/agent/.local/share",
             "--setenv", "OPENCODE_CONFIG", "/opt/opencode.json",
             "--setenv", "PATH", "/usr/bin:/bin:/opt:/home/ats030/.venv/bin",
             "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
             "--chdir", str(repo)]
    return args


def validated_replacements(response_text: str, files: list[str], worktree: Path) -> dict[str, str]:
    start, end = response_text.index("{"), response_text.rindex("}") + 1
    operations = json.loads(response_text[start:end])["replacements"]
    if not isinstance(operations, list) or not operations:
        raise ValueError("empty replacements")
    drafts = {name: (worktree / name).read_text(encoding="utf-8") for name in files}
    for operation in operations:
        name, old, new = operation["file"], operation["old"], operation["new"]
        if (name not in files or not isinstance(old, str) or not isinstance(new, str)
                or not old or old == new or drafts[name].count(old) != 1):
            raise ValueError(f"unsafe or non-unique replacement in {name}")
        drafts[name] = drafts[name].replace(old, new, 1)
    return drafts


def one_pass_file(repo: Path, worktree: Path, name: str) -> Path:
    """Allow only a regular tracked file at the same path in both trees."""
    relative = Path(name)
    if (relative.is_absolute() or name != relative.as_posix()
            or any(part in ("..", ".") or part.startswith(".") for part in relative.parts)):
        raise RuntimeError(f"invalid one-pass file: {name}")
    source = repo / relative
    draft = worktree / relative
    if (source.resolve() != source or draft.resolve() != draft
            or not source.is_file() or not draft.is_file()):
        raise RuntimeError(f"invalid one-pass file: {name}")
    tracked = command(["git", "ls-files", "--error-unmatch", "--", name], cwd=repo)
    if tracked.returncode:
        raise RuntimeError(f"one-pass file is not tracked: {name}")
    return draft


def one_pass(issue: dict, worktree: Path, repo: Path, files: list[str],
             model_name: str, provider: dict, run_dir: Path, timeout: int) -> int:
    """Ask Ollama for exact replacements; apply them only after exact checks."""
    base_url = provider["options"]["baseURL"].rstrip("/")
    if base_url != "http://localhost:11434/v1":
        raise RuntimeError("one-pass pilot requires the existing local Ollama proxy")
    sources = []
    source_bytes = 0
    for name in files:
        contents = one_pass_file(repo, worktree, name).read_text(encoding="utf-8")
        source_bytes += len(contents.encode())
        if source_bytes > 100_000:
            raise RuntimeError("one-pass source files exceed 100 KB")
        sources.append(f"### {name}\n{contents}")
    request_prompt = (
        "Return only valid JSON with this shape: "
        '{"replacements":[{"file":"icons.py","old":"exact old text","new":"exact new text"}]}. '
        "Each old text must occur exactly once in the provided file. "
        "Change only the provided files. Do not claim tests passed. "
        "Keep the fix as small as the acceptance criteria allow.\n\n"
        f"Issue {issue['id']}: {issue['title']}\n"
        f"Description: {issue.get('description', '')}\n"
        f"Acceptance: {issue['acceptance_criteria']}\n\n"
        + "\n\n".join(sources)
    )
    payload = json.dumps({"model": model_name.split("/", 1)[1], "stream": False,
                          "messages": [{"role": "user", "content": request_prompt}],
                          "temperature": 0, "max_tokens": 4096}).encode()
    request = urllib.request.Request(base_url + "/chat/completions", data=payload,
                                     headers={"Content-Type": "application/json",
                                              "X-Client-App": "opencode"})
    response_text = ""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(2):
        try:
            with opener.open(request, timeout=timeout) as response:
                response_text = json.loads(response.read())["choices"][0]["message"]["content"]
            if not isinstance(response_text, str):
                raise RuntimeError("model returned non-text content")
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 503 and attempt == 0:
                time.sleep(30)
                continue
            (run_dir / "model.stderr.log").write_text(f"HTTP {exc.code}: {exc.read()[:300]!r}\n")
            return 69
    (run_dir / "model.stdout.log").write_text(response_text)
    try:
        drafts = validated_replacements(response_text, files, worktree)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        (run_dir / "model.stderr.log").write_text(f"replacement validation: {exc}\n")
        return 65
    for name, content in drafts.items():
        path = worktree / name
        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issue_id")
    parser.add_argument("--repo", required=True, help="repository path relative to /home/ats030")
    parser.add_argument("--test", action="append", required=True, help="fixed test command, without shell syntax")
    parser.add_argument("--read-only", action="append", default=[], help="support file relative to /home/ats030")
    parser.add_argument("--one-pass-file", action="append", default=[],
                        help="tracked file to provide to a single Ollama patch request")
    parser.add_argument("--model-timeout", type=int, default=1200)
    args = parser.parse_args()
    if not ISSUE_ID.fullmatch(args.issue_id):
        parser.error("invalid issue ID")
    issue = issue_record(args.issue_id)
    repo = repository(args.repo)
    support = []
    for raw in args.read_only:
        source = (ROOT / raw).resolve()
        if (not source.is_relative_to(ROOT) or not source.is_file()
                or any(part.startswith(".") for part in source.relative_to(ROOT).parts)):
            parser.error("--read-only requires an ordinary file under the workspace")
        support.append(source)
    support_before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in support}
    if not OPENCODE.is_file() or not VENV.is_dir():
        raise RuntimeError("local OpenCode binary and Python environment are required")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RESULTS / f"{args.issue_id}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    worktree, state = run_dir / "worktree", run_dir / "agent-home"
    state.mkdir(mode=0o700)
    created = command(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], cwd=repo, timeout=120)
    if created.returncode:
        raise RuntimeError(f"worktree creation failed: {created.stderr.strip()[:300]}")

    user_config = json.loads((ROOT / ".config/opencode/opencode.json").read_text())
    model_name = user_config["model"]
    source_provider = user_config["provider"]["ollama"]
    source_options = source_provider["options"]
    if source_options.get("baseURL") != "http://localhost:11434/v1":
        raise RuntimeError("local Ollama proxy configuration is required")
    provider = {"npm": "@ai-sdk/openai-compatible", "name": "Ollama",
                "options": {"baseURL": source_options["baseURL"],
                            "timeout": source_options.get("timeout", 600000),
                            "chunkTimeout": source_options.get("chunkTimeout", 300000),
                            "headers": {"X-Client-App": "opencode"}},
                "models": source_provider["models"]}
    config = {
        "model": model_name, "small_model": model_name, "autoupdate": False,
        "provider": {"ollama": provider},
        "permission": {"bash": "deny", "external_directory": "deny", "webfetch": "deny",
                       "websearch": "deny", "task": "deny", "edit": "allow"},
        "agent": {"build": {"steps": 40}},
    }
    (run_dir / "opencode.json").write_text(json.dumps(config, ensure_ascii=False))
    prompt = (
        "次のBeads issueについて小さな修正案を作成してください。対象はこの作業ディレクトリだけです。"
        "コードと必要なテストを編集してください。コミット、push、デプロイ、外部操作、"
        "Beads更新をしないでください。シェルは使用できません。"
        "完了を主張せず、変更点と未検証の点を簡潔に説明してください。\n\n"
        f"ID: {issue['id']}\nTitle: {issue['title']}\n"
        f"Description: {issue.get('description', '')}\n"
        f"Acceptance: {issue['acceptance_criteria']}"
    )
    base = sandbox(worktree, state, support, repo)
    isolation = command(base + ["/usr/bin/python3", "-c",
                                "from pathlib import Path; "
                                "assert not Path('/home/ats030/.env').exists(); "
                                "assert not Path('/home/ats030/.ssh').exists(); "
                                "assert not Path('/home/ats030/.git').exists()"], cwd=repo)
    if isolation.returncode:
        raise RuntimeError(f"sandbox isolation failed: {isolation.stderr.strip()[:300]}")
    try:
        if args.one_pass_file:
            model_code = one_pass(issue, worktree, repo, args.one_pass_file,
                                  model_name, provider, run_dir, args.model_timeout)
        else:
            model = command(base + ["/opt/opencode", "run", "--model", model_name, prompt],
                            cwd=repo, timeout=args.model_timeout)
            (run_dir / "model.stdout.log").write_text(model.stdout)
            (run_dir / "model.stderr.log").write_text(model.stderr)
            model_code = model.returncode
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        model_code = 124
        if isinstance(exc, subprocess.TimeoutExpired):
            partial = exc.stdout or b""
            (run_dir / "model.stdout.log").write_bytes(
                partial.encode() if isinstance(partial, str) else partial)
        (run_dir / "model.stderr.log").write_text(f"timed out after {args.model_timeout}s: {exc}\n")

    tests = []
    for test in args.test:
        argv = shlex.split(test)
        if not argv or argv[0] not in ("python", "python3", "pytest", "/home/ats030/.venv/bin/python"):
            parser.error("tests must invoke Python or pytest directly")
        if argv[0] in ("python", "python3", "pytest"):
            argv[0] = "/home/ats030/.venv/bin/python"
            if test.startswith("pytest "):
                argv.insert(1, "-m")
                argv.insert(2, "pytest")
        try:
            completed = command(base + argv, cwd=repo, timeout=300)
            tests.append({"command": test, "exit_code": completed.returncode,
                          "stdout": completed.stdout[-8000:], "stderr": completed.stderr[-4000:]})
        except subprocess.TimeoutExpired:
            tests.append({"command": test, "exit_code": 124,
                          "stdout": "", "stderr": "test timed out after 300s"})

    diff = command(["git", "diff", "--binary"], cwd=worktree)
    whitespace = command(["git", "diff", "--check"], cwd=worktree)
    (run_dir / "changes.patch").write_text(diff.stdout)
    changed = command(["git", "status", "--short"], cwd=worktree)
    untracked = command(["git", "ls-files", "--others", "--exclude-standard"], cwd=worktree)
    support_after = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in support}
    passed = (model_code == 0 and diff.returncode == 0 and bool(diff.stdout)
              and whitespace.returncode == 0 and not untracked.stdout.strip()
              and support_before == support_after
              and all(t["exit_code"] == 0 for t in tests))
    report = {"issue_id": args.issue_id, "source_repository": str(repo),
              "source_head": command(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip(),
              "model": model_name, "mode": "one_pass" if args.one_pass_file else "opencode",
              "model_exit_code": model_code, "success": passed,
              "model_error": (run_dir / "model.stderr.log").read_text()[:500]
              if (run_dir / "model.stderr.log").exists() else "",
              "changed_files": changed.stdout.splitlines(), "tests": tests,
              "untracked_files": untracked.stdout.splitlines(),
              "diff_check_exit_code": whitespace.returncode,
              "support_sha256": support_before,
              "support_unchanged": support_before == support_after,
              "worktree": str(worktree), "run_dir": str(run_dir)}
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"issue_id": args.issue_id, "run_dir": str(run_dir),
                      "model_exit_code": model_code, "changed_files": report["changed_files"],
                      "test_exit_codes": [t["exit_code"] for t in tests]},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
