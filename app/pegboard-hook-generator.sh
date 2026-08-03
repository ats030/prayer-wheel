#!/bin/sh
# 有孔ボードフック ジェネレータ (port 8521)
# 完全な静的ファイルなので uvicorn は使わず標準ライブラリだけで配信する。
# pCloudDrive を参照しないので FUSE ストールの影響を受けない (ats030-e5z7)。
set -eu
TAILNET_IP="$(tailscale ip -4 | head -n 1)"
test -n "$TAILNET_IP"
cd "$HOME"
exec python3 -m http.server 8521 \
  --bind "$TAILNET_IP" \
  --directory /home/ats030/app/pegboard-hook-generator
