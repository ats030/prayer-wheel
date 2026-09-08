# Agent Instructions

This project uses **bd** (beads) for issue tracking. Use the quick reference below; run `bd prime` only when Beads context is missing or stale.

## Non-Interactive Shell Commands

Always use non-interactive forms: `cp -f`, `mv -f`, `rm -f`/`rm -rf`,
`scp -o BatchMode=yes`, `ssh -o BatchMode=yes`, `apt-get -y`, and
`HOMEBREW_NO_AUTO_UPDATE=1 brew ...`.

## Efficient High-Quality Workflow

- Keep one issue per session; restart when the objective changes.
- Before editing, derive outcome, checks, and scope from the issue or repository.
- For narrow work, use `rg` and relevant ranges. Skip generated trackers, lockfiles, build output, indexes, minified assets, and full logs unless relevant.
- Prefer targeted tests, `git diff --check`, API/HTTP responses, service state over prose.
- Offer at most three alternatives; recommend first with reason and drawback. Bound tool output and inspect the first causal error before widening.
- Improve context and validation before changing model, context, compaction, or reasoning settings.
- Before reporting work complete, run `git diff --stat` and confirm every changed file is in scope; drop or revert anything that isn't.
- Notice an unrequested defect mid-task? Fix it in the original issue only when every condition holds: it blocks the requested outcome or reproduces in the same component or call path; there is reproducible evidence for the symptom and cause; it does not materially expand an API, data format, permission boundary, external operation, or product decision; and the original task's validation can prove the fix. Add a comment to the original issue with the symptom, fix, and validation. Separate it from the requested change in the commit and final handoff.
- For an unrequested issue outside those conditions, create a linked issue with `bd create --deps discovered-from:<id>` and continue the original issue. If the boundary is unclear, treat it as separate work.
- After a non-trivial implementation, run `/code-review` (medium) before declaring the task done.

<!-- BEGIN BEADS INTEGRATION v:1 profile:full hash:f65d5d33 -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Quality
- Use `--acceptance` and `--design` fields when creating issues
- Use `--validate` to check description completeness

### Lifecycle
- `bd defer <id>` / `bd supersede <id>` for issue management
- `bd stale` / `bd orphans` / `bd lint` for hygiene
- `bd human <id>` to flag for human decisions
- `bd formula list` / `bd mol pour <name>` for structured workflows

### Auto-Sync

bd automatically records changes in local Dolt history:

- Each write auto-commits to Dolt history
- Use `bd dolt push`/`bd dolt pull` only when a Dolt remote is configured
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push  # only if a Dolt remote is configured
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->

## Agent Input Budget

- Exclude regenerated trackers, lockfiles, build output, indexes, and minified assets from routine diff review unless the task concerns them.
- For a narrow question, locate the symbol with `rg` and read only the relevant range. Read a large file in full only when its overall structure is required.

## visit-log

- New self-hosted web apps must include this tag in every HTML entry point, with the service/repository name as `data-site`:
  `<script src="http://ubuntu-server-app:8526/v.js" data-site="SERVICE_NAME" defer></script>`
- `app/deploy.sh` verifies the rendered HTML after restart and rejects an untagged deployment.
- Do not weaken CSP or inject code into generated output to satisfy the check. For a non-HTML app or a deliberate CSP/public-network exception, deploy with a non-empty `VISIT_LOG_EXEMPT_REASON` and record the reason in its issue.

## Cross-Agent Context Adapters

`AGENTS.md` is the canonical shared instruction file for Codex and OpenCode.
Claude Code imports it through a generated adapter. Content changes require no
adapter regeneration. To verify the adapters, run:

```bash
scripts/check-agent-context.sh
```

Run `scripts/sync-agent-context.sh` only for initial setup or repair.
Do not directly edit the generated adapter content in `~/.claude/CLAUDE.md` or
the managed `instructions` entry in `~/.config/opencode/opencode.json`.
