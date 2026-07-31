#!/bin/sh
set -e

cd "/home/ats030"

exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/pCloudDrive/Python/x-post app:app --host 0.0.0.0 --port 8502
