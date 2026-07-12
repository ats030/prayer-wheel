#!/bin/sh
set -e

cd "$HOME"

# pCloudDrive (FUSE) 上では venv 作成が失敗するため、ローカルに venv を配置する
export UV_PROJECT_ENVIRONMENT="$HOME/.venv/image-generator"
export PYTHONPATH="$HOME/app/app-hub/src${PYTHONPATH:+:$PYTHONPATH}"

exec /home/ats030/.local/bin/uv run \
    --directory ~/pCloudDrive/Python/image_generator \
    streamlit run app.py --server.port 8512
