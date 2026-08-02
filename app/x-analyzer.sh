#!/bin/sh
set -eu
if [ -f "/home/ats030/.env" ]; then set -a; . "/home/ats030/.env"; set +a; fi
cd "/home/ats030/app/x-analyzer"
export PYTHONPATH="/home/ats030/app/x-analyzer/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$HOME/.venv/bin/python" -m uvicorn app:app --host 0.0.0.0 --port 8503
