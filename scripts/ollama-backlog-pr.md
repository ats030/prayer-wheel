# Ollama backlog draft PR experiment

This is a manually started experiment. It extends `ollama-backlog-draft.py`.
The systemd user units exist; after the first pilot passed (`ats030-hbu8`,
app-portal PR #1), the user enabled the hourly timer on 2026-10-03, choosing
to start the candidate scan now and let later passes be reviewed. Each tick
handles one eligible issue. `backlog-viewer` remains read-only; Beads is the
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

When creating a new issue that already fits these conditions, write the
acceptance criteria for one approach, add the `ollama-draft-pr` label, add the
`scripts/ollama-backlog-pr.json` entry in the same change, and mention the label
in the session handoff. This builds the supply of eligible issues; the runner
itself still never adds the label.

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

On success (`draft_pr_created`) and on a real failure (generation, publish,
or an unhandled exception), a single-line Discord notification is posted to
the `DISCORD_WEBHOOK_URL` in `~/.env` (best-effort; a failed webhook does not
change the exit code). Designed no-ops (`no_eligible_issue`,
`already_attempted`) and transient `busy` do not send a notification, so an
hourly tick with nothing to do stays quiet.

## Timer state

The manual pilots are tracked in `ats030-w1yb` (deferred) and `ats030-nvzr`
(open review follow-up). A pilot passes when its draft PR merges with no or
only minor edits. One pilot has passed (`ats030-hbu8`, app-portal PR #1,
squash-merge `5fd9373`). The user chose to start the candidate scan after that
first pass rather than waiting for three, so on 2026-10-03 the timer was
enabled with:

```bash
systemctl --user enable --now ollama-backlog-pr.timer
```

The units `ollama-backlog-pr.service`,
`ollama-backlog-pr.service.d/failure-policy.conf`, and `ollama-backlog-pr.timer`
(hourly, `OnCalendar=hourly`) run one runner per tick; a tick with no eligible
issue exits with `no_eligible_issue` and `already_attempted` prevents the same
issue from being published twice. Disable the timer if a recent draft PR fails
review or if two consecutive attempts fail.
