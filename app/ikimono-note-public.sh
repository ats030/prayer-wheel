#!/bin/sh
set -eu
# 一般公開版 (Tailscale Funnel の向け先)。運営者の設定変更は 403 で拒否し、
# APIキーは各利用者のブラウザに置く BYOK で動かす。
# 運営者用は ikimono-note.sh (8523) が担う。
IKIMONO_PUBLIC_MODE=1
export IKIMONO_PUBLIC_MODE
export IKIMONO_PUBLIC_LOCAL="${IKIMONO_PUBLIC_LOCAL:-0}"
export IKIMONO_PUBLIC_AFFILIATE="${IKIMONO_PUBLIC_AFFILIATE:-0}"
# Funnel からしか来ないので、Hostは公開ホスト名とループバックだけ通す。
export IKIMONO_ALLOWED_HOSTS="${IKIMONO_PUBLIC_ALLOWED_HOSTS:-ubuntu-server-app.tailf74832.ts.net,127.0.0.1,localhost}"
# 127.0.0.1 で待つ。LANや他ホストから公開版へ直接つなげる経路を作らない。
exec /home/ats030/.local/bin/uv run uvicorn --app-dir /home/ats030/app/ikimono-note main:app \
  --host 127.0.0.1 --port 8524 --timeout-graceful-shutdown 5 --no-access-log
