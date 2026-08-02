#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run ~/app/web-clipper/main.py --server.port 8501

