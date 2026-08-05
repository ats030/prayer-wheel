#!/bin/sh
set -e

cd "$HOME"

# Runs from the local checkout under ~/app, not a pCloud FUSE working copy, so a
# FUSE stall can't fault the process (same arrangement as writing.sh /
# rss-reader.sh). This app lives in the home repository, so there is no git pull
# on startup: deploying it is an ordinary commit here.
export PYTHONPATH="$HOME/app/exam-trainer/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run uvicorn exam_trainer.app:app \
  --host 0.0.0.0 --port 8522 --timeout-graceful-shutdown 5
