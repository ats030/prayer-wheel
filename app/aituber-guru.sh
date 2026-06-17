#!/bin/sh
set -e

cd "$HOME"

# aituber-guru のリポジトリは pCloud(FUSE) 上にあり、そこには pyproject.toml が無い。
# uv は親へ遡って ~/pyproject.toml を解決し、共有の ~/.venv を使う
# （fastapi/uvicorn/jinja2/requests 等はそこに既に入っている）。
# --directory でプロジェクトルートに入り、src パッケージと .env を解決する。
exec /home/ats030/.local/bin/uv run \
    --directory ~/pCloudDrive/Python/aituber-guru \
    uvicorn src.webapp:app --host 0.0.0.0 --port 8511
