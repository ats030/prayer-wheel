#!/bin/sh
set -eu

TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"

cd "$HOME"

# pCloudDrive (FUSE) 上では venv 作成が失敗するため、ローカルに venv を配置する
export UV_PROJECT_ENVIRONMENT="$HOME/.venv/image-generator"
export PYTHONPATH="$HOME/app/app-hub/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run \
    --directory /home/ats030/image-generator-work \
    uvicorn main:app --host "$TAILNET_IP" --port 8512
