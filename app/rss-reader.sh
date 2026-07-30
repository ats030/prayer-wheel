#!/bin/sh
set -e

cd "$HOME"

# Runs from the local checkout under ~/app, not the pCloud FUSE working copy, so
# a FUSE stall can't fault the process and static assets serve from local disk
# (same arrangement as writing.sh).
export PYTHONPATH="$HOME/app/rss-reader/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run uvicorn rss_reader.app:app \
  --host 0.0.0.0 --port 8505 --timeout-graceful-shutdown 5
