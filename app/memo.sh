#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run ~/app/memo/main.py --server.port 8509
