# Ollama backlog draft pilot

`ollama-backlog-draft.py` takes one Beads issue ID, an `app/<repository>` Git
repository, fixed test commands, and any supporting files the tests need. The
issue must be open, have acceptance criteria, and lack `human` and `decision`
labels. The source repository must be clean.

The script creates a detached worktree under `~/data/ollama-backlog/`. OpenCode
uses the configured Ollama model to edit that worktree. It has no shell tool,
normal home directory, mounted Git repository metadata, Beads executable, or
credentials in its filesystem view. Only the worktree and a temporary OpenCode
home are writable.
Network access remains available for the local Ollama proxy. Tests run in the
same filesystem view, so choose reviewed, fixed test commands and review any
test edits before accepting the result. The script does not claim or close the Beads issue,
commit, push, deploy, or copy the draft into the source repository.

The run directory contains `changes.patch`, `report.json`, model logs, and the
worktree. Review the diff and test results before deciding what to apply. A
nonzero exit or an empty diff is a failed draft, even when tests pass. Remove
old worktrees with `git -C app/<repository> worktree remove <path>` after
review; do not delete their directories directly because Git tracks them.

The completed first trial used `ats030-nbqc` in `app/app-portal`, with
`python -m pytest -q test_icons.py`. That test reads favicons in sibling apps,
so its invocation supplies those files through repeated `--read-only` options.
Each option mounts one file read-only at its normal path inside the sandbox.
`scripts/ollama-backlog-pilot-nbqc.sh` preserves that invocation; it now stops
at the eligibility check because the issue is closed. For a new issue, pass its
open ID, repository, fixed tests and any support files to the Python runner.
When OpenCode's tool loop is too slow, `--one-pass-file` supplies exact tracked
files to one Ollama request. The response must contain JSON string replacements;
each old string must match exactly once, and selected files must be regular,
tracked files without symlink traversal. The script then creates the Git diff
locally and runs the same tests. A malformed response is rejected.
`success: true` in `report.json` means the mechanical checks passed. Review the
issue description against the diff before accepting the draft.

The installed Bubblewrap 0.9.0 is reused; no package is added. Its source is
LGPL-2.0-or-later, which permits this use at no software license cost. See the
[upstream v0.9.0 source license](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)
and the [project security note](https://github.com/containers/bubblewrap/security):
the caller defines the filesystem and network policy. This pilot does not
isolate the network, so it must not be presented as a full network sandbox.
