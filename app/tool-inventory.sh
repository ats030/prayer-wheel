#!/bin/sh
set -eu
TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"
cd "$HOME"
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/pCloudDrive/Python/tool-inventory main:app --host "$TAILNET_IP" --port 8518
