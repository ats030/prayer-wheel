#!/bin/sh
# 残タスクの週次サマリを Discord へ送る (日曜朝8時 JST)。
# 終了コード: 0=送った / 3=Webhook未設定 (SuccessExitStatus=3) / 1=障害
set -eu
cd "$HOME"
exec /home/ats030/.local/bin/uv run python /home/ats030/app/backlog-viewer/notify.py
