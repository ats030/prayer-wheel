#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run python /home/ats030/pCloudDrive/Python/usage-viewer/main.py
