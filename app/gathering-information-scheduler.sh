#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run \
    python ~/app/gathering-information/scheduler_main.py
