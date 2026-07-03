#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run python ~/pCloudDrive/Python/app-portal/main.py
