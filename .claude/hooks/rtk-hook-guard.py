#!/usr/bin/env python3
"""PreToolUse guard in front of `rtk hook claude`.

rtk rewrites some Bash commands to their `rtk <cmd>` equivalent and returns
permissionDecision "allow" for every one of them. That is fine for read-only
commands, but it also silently skips the permission prompt for commands that
publish or destroy work. Measured on rtk 0.43.0 (2026-08-18):

    git push origin main       -> rewritten, allow
    git push --force ...       -> rewritten, allow
    git commit -m x            -> rewritten, allow
    git branch -D feature      -> rewritten, allow
    rm -rf ...                 -> not rewritten (prompt kept)
    git reset --hard ...       -> not rewritten (prompt kept)
    git clean -fdx             -> not rewritten (prompt kept)

This wrapper passes those four through untouched, so Claude Code applies its
normal permission flow, and delegates everything else to rtk unchanged. None of
the excluded commands appear among rtk's top token savers, so the cost is
effectively zero.

Fails open to the *safe* side: on any error it emits nothing, which means the
normal permission flow applies and only the token saving is lost.

Rollback: point the PreToolUse hook back at `rtk hook claude`.
"""

import json
import re
import subprocess
import sys

RTK = "/home/ats030/.local/bin/rtk"

# Commands rtk rewrites AND that must keep their permission prompt.
GUARDED = re.compile(
    r"""^\s*                      # leading space
        (?:[A-Za-z_][\w]*=\S*\s+)*  # optional VAR=value prefixes
        git\s+
        (?: push\b
          | commit\b
          | branch\b (?=.*(?:\s-[dD]\b|\s--delete\b))
        )""",
    re.VERBOSE,
)


def main() -> int:
    raw = sys.stdin.read()

    try:
        command = json.loads(raw).get("tool_input", {}).get("command", "")
    except Exception:
        return 0  # unparseable: let the normal flow handle it

    if isinstance(command, str) and GUARDED.search(command):
        return 0  # no rewrite, no auto-allow -> Claude Code prompts as usual

    try:
        done = subprocess.run(
            [RTK, "hook", "claude"],
            input=raw,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return 0

    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
