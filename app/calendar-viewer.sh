#!/bin/sh
set -eu
export UV_PROJECT_ENVIRONMENT=/home/ats030/.venv/calendar-viewer
export UV_CACHE_DIR=/tmp/calendar-viewer-uv-cache
exec /home/ats030/.local/bin/uv run --directory /home/ats030/app/calendar-viewer uvicorn calendar_viewer.app:app --host 127.0.0.1 --port 8515
