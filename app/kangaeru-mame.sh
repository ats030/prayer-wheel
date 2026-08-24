#!/bin/sh
set -e

cd "$HOME"

# Keep uv bound to the renamed local checkout so systemd does not resolve an old path.
# The project environment is regenerated after a directory rename.
export UV_PROJECT_ENVIRONMENT=/home/ats030/kangaeru-mame/.venv

exec /home/ats030/.local/bin/uv run \
    --directory /home/ats030/kangaeru-mame \
    uvicorn src.webapp:app --host 0.0.0.0 --port 8511
