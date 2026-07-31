#!/bin/bash
set -euo pipefail

cd /home/ats030/pCloudDrive/Python/patent-miner
export UV_PROJECT_ENVIRONMENT=/home/ats030/.venv/patent-miner
exec /home/ats030/.local/bin/uv run uvicorn app:app --host 0.0.0.0 --port 8506
