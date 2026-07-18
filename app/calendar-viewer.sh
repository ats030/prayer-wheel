#!/bin/sh
set -eu
TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"
export UV_PROJECT_ENVIRONMENT=/home/ats030/.venv/calendar-viewer
exec /home/ats030/.local/bin/uv run --directory /home/ats030/pCloudDrive/Python/calendar-viewer uvicorn calendar_viewer.app:app --host "$TAILNET_IP" --port 8515
