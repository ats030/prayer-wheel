#!/bin/sh
set -e

cd "$HOME"

# コードはローカルチェックアウトから実行する。pCloudDrive (rclone FUSE) 上の .py を
# 直接動かすと、起動後もページフォルトで触りうるため FUSE ストール時にプロセスが
# ハングする (ats030-e5z7)。データは ~/data/usage-viewer/ (ats030-tdup)。
exec /home/ats030/.local/bin/uv run python ~/app/usage-viewer/main.py
