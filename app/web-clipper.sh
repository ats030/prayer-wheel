#!/bin/sh
set -e

# 依存は ~/pyproject.toml (共有 ~/.venv) に集約しているため $HOME で uv run する。
# ポートはユニットの Description "(port 8501)" と app-portal が前提にしている番号。
# 手動起動はリポジトリ側の start.sh (同じ起動方法) を使う。
cd "$HOME"

exec /home/ats030/.local/bin/uv run ~/app/web-clipper/main.py --port 8501
