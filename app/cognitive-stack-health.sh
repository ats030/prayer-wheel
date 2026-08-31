#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run ~/pCloudDrive/Python/cognitive-stack-health/main.py --server.port 8504
