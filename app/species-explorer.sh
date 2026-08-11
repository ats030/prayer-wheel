#!/bin/sh
set -eu
# 8523 は運営者用。設定 (APIキー・モデル・広告) を保存できる非公開モードで動かす。
# 一般公開は species-explorer-public.sh (8524) が担い、Tailscale Funnel はそちらへ向ける。
# ここを公開モードにすると設定を保存できなくなるため、環境変数では上書きさせない。
SPECIES_PUBLIC_MODE=0
export SPECIES_PUBLIC_MODE
# 認証がないので、届く範囲は Tailscale と自宅LANに限る。Funnel はこのポートへ向けない。
export SPECIES_ALLOWED_HOSTS="${SPECIES_ALLOWED_HOSTS:-ubuntu-server-app.tailf74832.ts.net,100.94.207.13,192.168.11.9,127.0.0.1,localhost}"
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/species-explorer main:app \
  --host 0.0.0.0 --port 8523 --timeout-graceful-shutdown 5 --no-access-log
