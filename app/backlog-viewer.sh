#!/bin/sh
# backlog-viewer (port 8509) を Tailnet 限定で起動する。
# タスクのタイトルに認証情報の話題が含まれるため 0.0.0.0 では待たない。
set -eu
TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"
cd "$HOME"
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/backlog-viewer main:app \
  --host "$TAILNET_IP" --port 8509 --timeout-graceful-shutdown 5 --no-access-log
