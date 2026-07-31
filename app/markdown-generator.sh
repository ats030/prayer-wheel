#!/bin/sh
set -e

# ~/.env から必要な変数のみ抽出して読み込む（JSON値など特殊文字を含む行はスキップ）
if [ -f "/home/ats030/.env" ]; then
    _tmpenv=$(mktemp)
    grep -E '^(AMAZON_EMAIL|AMAZON_PASSWORD|KINDLE_REGION|OLLAMA_BASE_URL|OLLAMA_MODELS|OLLAMA_TIMEOUT|REDACT_WORDS|REDACT_PATTERNS)=' \
        /home/ats030/.env > "$_tmpenv" 2>/dev/null || true
    set -a
    . "$_tmpenv"
    set +a
    rm -f "$_tmpenv"
fi

# Kill any existing instance on port 8504
_pid=$(lsof -ti tcp:8504 2>/dev/null || true)
if [ -n "$_pid" ]; then
    kill "$_pid" 2>/dev/null || true
fi

cd "/home/ats030/pCloudDrive/Python/markdown-generator"
_py="$HOME/.venv/markdown-generator/bin/python"
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    exec xvfb-run -a "$_py" -m uvicorn app:app --host 0.0.0.0 --port 8504
else
    exec "$_py" -m uvicorn app:app --host 0.0.0.0 --port 8504
fi
