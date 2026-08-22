#!/bin/bash
set -euo pipefail

# コードはローカルチェックアウトから実行する。pCloudDrive (rclone FUSE) 上の .py を
# 直接動かすと、起動後もページフォルトで触りうるため FUSE ストール時にプロセスが
# ハングする (ats030-e5z7)。データは ~/data/<app>/ にある (ats030-vr6r)。
cd /home/ats030/app/patent-miner
export UV_PROJECT_ENVIRONMENT=/home/ats030/.venv/patent-miner
exec /home/ats030/.local/bin/uv run uvicorn app:app --host 0.0.0.0 --port 8506
