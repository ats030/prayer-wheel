# Ollama backlog draft PR experiment

This is a manually started experiment. It extends `ollama-backlog-draft.py` and
does not run on a timer. The first three real PRs must be reviewed before a
daily timer is considered. `backlog-viewer` remains read-only; Beads is the
source of truth for issue status and acceptance criteria.

## Opt in one issue

Choose a small code fix in a clean, independent `app/<repository>` Git
repository whose `origin` is GitHub. The issue must be open, unassigned,
unblocked (`bd ready`), have concrete acceptance criteria, and need no external
research, credentials, data migration, deployment, or product decision. Create
a small child issue from a broader item when necessary. A human reviews the
scope and then adds the `ollama-draft-pr` label. The automation never adds that
label itself.

The model sees only the issue description and acceptance criteria, not the
design field. If the acceptance criteria list alternatives, the model may pick
any of them (ats030-hbu8 run 1 deleted a `REMOTE_APPS` entry instead of adding
a cache). Rewrite the acceptance criteria to one approach before labeling.

Add an entry with the same issue ID to `scripts/ollama-backlog-pr.json`:

```json
{
  "schema_version": 1,
  "issues": {
    "ats030-example": {
      "repo": "app/app-portal",
      "base": "main",
      "files": ["icons.py"],
      "tests": ["python -m pytest -q test_icons.py"],
      "read_only": []
    }
  }
}
```

`files` are the only tracked, regular files that the model may change. The
experiment accepts at most three existing code files and 80 added/deleted
lines. Test files are excluded from the model's edit list. `tests` are fixed commands reviewed with the issue; they run in a
Bubblewrap network namespace without access to the normal home directory.
Support files are mounted read-only from `read_only`. The model uses a single
structured replacement request. It cannot run a shell or use GitHub/Beads
credentials.

Preview the next eligible issue:

```bash
python3 scripts/ollama-backlog-pr.py
```

After checking the preview, manually run one issue:

```bash
python3 scripts/ollama-backlog-pr.py --run --issue ats030-example
```

The host checks that the local base commit equals `origin/<base>`, the proxy
reports idle, the issue is still eligible, and no branch or PR exists for the
issue. After generation it checks the report, exact test commands, file list,
diff, file modes, line count, and source commit. Only then does it claim the
issue, push `ollama/<issue-id>`, and create a **draft** PR. It records the PR
URL in the run directory and comments on the Beads issue. A human reviews,
merges, and closes the issue. The automation never pushes `main`, merges,
deploys, or closes Beads issues.

If Ollama is busy, the proxy status endpoint is unavailable, generation fails,
or a gate fails, no PR is created. There is no automatic retry. The run report
and worktree remain under `~/data/ollama-backlog/` for inspection. If a push
succeeds but PR creation fails, the branch remains for manual recovery; the
next run will not overwrite it. This experiment does not delete branches or
old worktrees automatically.

The currently running Ollama proxy process predates the source code's
`/api/opencode-status` endpoint and returns HTML for that path. The runner
therefore reports `busy_unknown` and stops safely until the live endpoint is
verified (`ats030-i6la`). As of 2026-09-25, `gh auth status` also reports an
invalid GitHub CLI token (`ats030-499b`), so PR creation cannot be exercised
until that credential is renewed. The three manual pilots are tracked in
`ats030-w1yb`. Do not enable a timer until three manually reviewed PRs have passed
and the proxy busy check and cancellation behavior have been confirmed in the
running service.
