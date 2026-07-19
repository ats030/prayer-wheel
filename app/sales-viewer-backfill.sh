#!/bin/sh
set -eu
exec /home/ats030/.local/bin/uv run python backfill_booth.py 3
