#!/bin/sh
set -eu
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/species-explorer main:app --host 0.0.0.0 --port 8523 --timeout-graceful-shutdown 5
