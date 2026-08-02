#!/bin/sh
# コードは pCloudDrive ではなくローカルチェックアウト (~/app/app-portal) から実行する。
# pCloudDrive は FUSE のクラウド同期で、ストールすると稼働中のプロセスがページフォルトで
# ハングまたは落ちる (ats030-e5z7)。編集は pCloud 側で行い、push 後に
# app/deploy.sh app-portal で取り込む。
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run python /home/ats030/app/app-portal/main.py
