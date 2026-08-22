#!/bin/sh
# weather-viewer (port 8520)
#
# ソースは ~/app/weather-viewer (ローカルチェックアウト)。2026-08-22 に
# pCloudDrive から移した (ats030-e5z7)。依存は ~/pyproject.toml (uv sync) に
# あるものだけで、追加は無い。
set -e

cd "$HOME"

# コードはローカルチェックアウトから実行する。pCloudDrive (rclone FUSE) 上の .py を
# 直接動かすと、起動後もページフォルトで触りうるため FUSE ストール時にプロセスが
# ハングする (ats030-e5z7)。
export PYTHONPATH="$HOME/app/weather-viewer/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run uvicorn weather_viewer.app:app \
  --host 0.0.0.0 --port 8520 --timeout-graceful-shutdown 5
