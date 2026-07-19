#!/bin/sh
set -eu
exec /home/ats030/.local/bin/uv run python cults_watch.py
