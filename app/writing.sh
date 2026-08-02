#!/bin/sh
set -e

cd "$HOME"

# Run from the local checkout (not the pCloud FUSE working copy) so a FUSE
# stall can't fault the process and static assets serve from local disk.
# Deploy = git pull in ~/app/writing + restart (see scripts/deploy.sh).
export PYTHONPATH="$HOME/app/app-hub/src:$HOME/app/writing/src${PYTHONPATH:+:$PYTHONPATH}"

# Pull latest on startup so a plain `systemctl restart writing.service` picks up
# pushed changes without running scripts/deploy.sh by hand. Best-effort: a
# network/git hiccup must never stop the service from booting — BatchMode avoids
# an interactive auth hang, the timeout caps a stalled fetch, and `|| echo` keeps
# `set -e` from aborting on an offline or non-ff pull (we then serve as-is).
GIT_SSH_COMMAND="ssh -o BatchMode=yes" timeout 60 \
  git -C "$HOME/app/writing" pull --ff-only \
  || echo "writing.sh: git pull skipped (offline or non-ff); serving current checkout" >&2

exec /home/ats030/.local/bin/uv run uvicorn writing.app:app \
  --host 0.0.0.0 --port 8510 --timeout-graceful-shutdown 5
