#!/bin/sh
# visit-log (port 8526) を Tailnet 限定で起動する。
# 集計画面には各アプリの閲覧パスが並ぶので 0.0.0.0 では待たない。
# 計測タグを置くページも Tailnet 上のホスト名で参照するため、
# ループバックではなく Tailnet IP で待つ。
set -eu
TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"
cd "$HOME"
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/visit-log main:app \
  --host "$TAILNET_IP" --port 8526 --timeout-graceful-shutdown 5 --no-access-log
