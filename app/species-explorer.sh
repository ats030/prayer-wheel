#!/bin/sh
set -eu
export SPECIES_PUBLIC_MODE="${SPECIES_PUBLIC_MODE:-1}"
export SPECIES_PUBLIC_LOCAL="${SPECIES_PUBLIC_LOCAL:-0}"
export SPECIES_PUBLIC_AFFILIATE="${SPECIES_PUBLIC_AFFILIATE:-0}"
export SPECIES_ALLOWED_HOSTS="${SPECIES_ALLOWED_HOSTS:-ubuntu-server-app.tailf74832.ts.net,100.94.207.13,192.168.11.9,127.0.0.1,localhost}"
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/species-explorer main:app \
  --host 0.0.0.0 --port 8523 --timeout-graceful-shutdown 5 --no-access-log
