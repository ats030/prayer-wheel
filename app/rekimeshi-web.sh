#!/bin/bash
# rekimeshi 閲覧・設定Webアプリ (port 8514)
# venvはpCloud外 (~/.venv/rekimeshi)。systemd: rekimeshi-web.service
export PATH="$HOME/.local/bin:$PATH"  # systemd環境はuvのPATHを持たない
export UV_PROJECT_ENVIRONMENT="$HOME/.venv/rekimeshi"
exec uv run --directory "$HOME/pCloudDrive/Python/rekimeshi" \
  python -m uvicorn webapp.app:app \
  --host "${REKIMESHI_WEB_HOST:-0.0.0.0}" \
  --port "${REKIMESHI_WEB_PORT:-8514}"
