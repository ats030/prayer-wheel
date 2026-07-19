#!/bin/sh
set -eu
exec /home/ats030/.local/bin/uv run python run_booth_fetch.py
