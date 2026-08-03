#!/bin/sh
# weather-viewer (port 8520)
#
# ソースは ~/pCloudDrive/Python/weather-viewer に置いている。pCloud は FUSE
# なので、マウントが固まると uvicorn ごと止まる。systemd 側で
# home-ats030-pCloudDrive.mount を Requires= しているのはこのため。
# 依存は ~/pyproject.toml (uv sync) にあるものだけで、追加は無い。
set -e

cd "$HOME"

export PYTHONPATH="$HOME/pCloudDrive/Python/weather-viewer/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run uvicorn weather_viewer.app:app \
  --host 0.0.0.0 --port 8520 --timeout-graceful-shutdown 5
