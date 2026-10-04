#!/usr/bin/env python3
"""Read-only candidate ranking for the Ollama draft-PR pipeline.

Ranks ``bd ready`` issues by how close they are to the pipeline's hard
gates (independent app repo, GitHub origin, clean tree, main/master).
It never writes to beads, git, or the automation config.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/ats030")
CONFIG = ROOT / "scripts/ollama-backlog-pr.json"
GITHUB = (re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?$"),
          re.compile(r"^git@github\.com:[\w.-]+/[\w.-]+?(\.git)?$"))


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=30)


def repositories(issues: list[dict]) -> list[tuple[str, list[dict]]]:
    apps = sorted(p.name for p in (ROOT / "app").iterdir() if p.is_dir())
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in apps) + r")\b")
    groups: dict[str, list[dict]] = {}
    for issue in issues:
        text = " ".join(str(issue.get(key) or "") for key in
                        ("title", "description", "acceptance_criteria", "notes"))
        for name in sorted(set(pattern.findall(text))):
            groups.setdefault(name, []).append(issue)
    return sorted(groups.items())


def gates(repo: Path) -> dict:
    top = run(["git", "rev-parse", "--show-toplevel"], cwd=repo)
    independent = (top.returncode == 0
                   and Path(top.stdout.strip()).resolve() == repo)
    result = {"independent": independent, "github": False, "clean": False,
              "base_branch": None, "has_tests": False}
    if not independent:
        return result
    origin = run(["git", "remote", "get-url", "origin"], cwd=repo).stdout.strip()
    result["github"] = any(match.fullmatch(origin) for match in GITHUB)
    result["clean"] = not run(["git", "status", "--porcelain"],
                              cwd=repo).stdout.strip()
    branch = run(["git", "branch", "--show-current"], cwd=repo).stdout.strip()
    for base in ("main", "master"):
        if branch == base and run(["git", "ls-remote", "--heads", "origin",
                                   f"refs/heads/{base}"], cwd=repo).stdout.strip():
            result["base_branch"] = base
            break
    result["has_tests"] = ((repo / "tests").is_dir()
                           or bool(list(repo.glob("test_*.py"))
                                  + list(repo.glob("tests/test_*.py"))))
    return result


def score(issue: dict, gate: dict) -> int:
    value = 40 if gate["has_tests"] else 10
    value += max(0, 20 - 4 * int(issue.get("priority", 4)))
    if issue.get("design"):
        value += 5
    return value


def main() -> int:
    ready = json.loads(run(["bd", "ready", "--json", "--limit", "0"]).stdout)
    with_config = set()
    if CONFIG.is_file():
        with_config = set(json.loads(CONFIG.read_text(encoding="utf-8"))["issues"])
    ranked, parked, skipped = [], [], []
    for name, issues in repositories(ready):
        gate = gates(ROOT / "app" / name)
        repo_ok = (gate["independent"] and gate["github"] and gate["clean"]
                   and gate["base_branch"])
        for issue in issues:
            row = {"id": issue["id"], "title": issue["title"],
                   "priority": issue["priority"], "repo": f"app/{name}",
                   "labels": issue.get("labels") or [], "design": bool(issue.get("design")),
                   "gates": gate}
            if issue["id"] in with_config:
                row["state"] = "already_configured"
                skipped.append(row)
            elif "ollama-draft-pr" in row["labels"]:
                row["state"] = "labeled_not_configured"
                skipped.append(row)
            elif not issue.get("acceptance_criteria"):
                row["state"] = "needs_acceptance"
                parked.append(row)
            elif not repo_ok:
                row["state"] = "repo_gates_fail"
                parked.append(row)
            elif len(issues) > 1:
                row["state"] = "ambiguous_repo"
                parked.append(row)
            else:
                row["state"] = "ready"
                row["score"] = score(issue, gate)
                ranked.append(row)
    ranked.sort(key=lambda row: (-row["score"], row["priority"], row["id"]))
    report = {"ready": ranked, "parked": parked, "skipped": skipped}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
