#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 scripts/build-cloudflare.py
"${MIDOKORO_NODE:-$HOME/.nvm/versions/node/v24.19.0/bin/node}" --test scripts/test-cloudflare.mjs
python3 scripts/run-cloudflare.py deploy
