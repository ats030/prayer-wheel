#!/usr/bin/env python3
"""Exercise the OpenCode tmux launcher with fake tmux and OpenCode binaries."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

LAUNCHER = Path(__file__).with_name("opencode-tmux.sh")


def run_case(*, tmux_env: str, has_session: bool, args: list[str]) -> list[str]:
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        log = tmp / "calls"
        fake_tmux = tmp / "tmux"
        fake_opencode = tmp / "opencode-real"
        fake_tmux.write_text(
            """#!/bin/sh
printf 'tmux:%s\\n' "$*" >>"$TEST_LOG"
if [ "$1" = display-message ]; then
  printf 'work\\n'
  exit 0
fi
if [ "$1" = has-session ]; then
  exit "$HAS_SESSION"
fi
exit 0
""",
            encoding="utf-8",
        )
        fake_opencode.write_text(
            """#!/bin/sh
printf 'real:%s\\n' "$*" >>"$TEST_LOG"
""",
            encoding="utf-8",
        )
        fake_tmux.chmod(0o755)
        fake_opencode.chmod(0o755)
        env = {
            **os.environ,
            "TEST_LOG": str(log),
            "HAS_SESSION": "0" if has_session else "1",
            "OPENCODE_TMUX": str(fake_tmux),
            "OPENCODE_REAL": str(fake_opencode),
            "OPENCODE_STATUS_SCRIPT": "/status.py",
            "OPENCODE_SESSION_NAME": "opencode",
            "TMUX": tmux_env,
        }
        subprocess.run([str(LAUNCHER), *args], check=True, env=env)
        return log.read_text(encoding="utf-8").splitlines()


inside = run_case(tmux_env="/tmp/tmux,1,0", has_session=False,
                  args=["--model", "ollama/qwen3.8:27b"])
assert "tmux:display-message -p #S" in inside
assert "real:--model ollama/qwen3.8:27b" in inside
assert not any("new-session" in line for line in inside)

existing = run_case(tmux_env="", has_session=True, args=[])
assert existing == [
    "tmux:has-session -t =opencode",
    "tmux:attach-session -t =opencode",
]

created = run_case(tmux_env="", has_session=False, args=["--continue"])
assert any(
    "new-session -d -s opencode -c /home/ats030 " in line
    and line.endswith(" --continue")
    for line in created
)
assert created[-1] == "tmux:attach-session -t =opencode"
print("opencode tmux launcher self-test: ok")
