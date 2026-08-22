#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/gathering-information app:app --host 0.0.0.0 --port 8508
