#!/bin/sh
set -e

# omatsuri-map: 神社・お祭りマップ表示アプリ (port 8527)
# Go言語のREST APIサーバーを8527ポートで起動
# コードはローカルチェックアウト (~/app/omatsuri-map) から実行

cd /home/ats030/app/omatsuri-map

# 宿リンクに必要な設定だけを読み込む（他の .env 設定は取り込まない）。
if [ -f /home/ats030/.env ]; then
    _omatsuri_env=$(mktemp)
    grep -E '^JALAN_A8MAT=' /home/ats030/.env > "$_omatsuri_env" 2>/dev/null || true
    set -a
    . "$_omatsuri_env"
    set +a
    rm -f "$_omatsuri_env"
fi

exec /home/ats030/app/omatsuri-map/omatsuri-map-server
