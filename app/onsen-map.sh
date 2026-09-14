#!/bin/sh
set -e

# onsen-map: 温泉マップ表示アプリ (port 8528)
# Go言語のREST APIサーバーを8528ポートで起動
# コードはローカルチェックアウト (~/app/onsen-map) から実行

cd /home/ats030/app/onsen-map

# ~/.env から必要な変数のみ抽出して読み込む（JSON値など特殊文字を含む行はスキップ）
if [ -f "/home/ats030/.env" ]; then
    _tmpenv=$(mktemp)
    grep -E '^(JALAN_API_KEY|JALAN_A8MAT)=' \
        /home/ats030/.env > "$_tmpenv" 2>/dev/null || true
    set -a
    . "$_tmpenv"
    set +a
    rm -f "$_tmpenv"
fi

exec /home/ats030/app/onsen-map/app-server
