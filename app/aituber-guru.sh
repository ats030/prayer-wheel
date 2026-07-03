#!/bin/sh
set -e

cd "$HOME"

# The repo lives on pCloud(FUSE), and a stale repo-local .venv can make uv abort.
# Use the shared user venv explicitly so systemd startup is stable.
export UV_PROJECT_ENVIRONMENT=/home/ats030/.venv

exec /home/ats030/.local/bin/uv run \
    --directory /home/ats030/pCloudDrive/Python/aituber-guru \
    uvicorn src.webapp:app --host 0.0.0.0 --port 8511
