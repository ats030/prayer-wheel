#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run ~/app/image-editor/main.py --server.port 8513
