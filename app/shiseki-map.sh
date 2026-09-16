#!/bin/sh
set -e
cd /home/ats030/app/shiseki-map
if [ -f /home/ats030/.env ]; then
  _shiseki_env=$(mktemp)
  grep -E '^(JALAN_A8MAT|OLLAMA_MODEL)=' /home/ats030/.env > "$_shiseki_env" 2>/dev/null || true
  set -a
  . "$_shiseki_env"
  set +a
  rm -f "$_shiseki_env"
fi
exec /home/ats030/app/shiseki-map/app-server
