#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 build_cloudflare_app.py
python3 -m unittest test_cloudflare_credentials test_build_cloudflare test_build_cloudflare_app
if [ "${1:-}" = "--deploy" ]; then
  python3 run_cloudflare.py deploy --config wrangler-app.jsonc
elif [ "$#" = 0 ]; then
  python3 run_cloudflare.py deploy --config wrangler-app.jsonc --dry-run
else
  printf 'Usage: bash deploy-cloudflare-app.sh [--deploy]\n' >&2
  exit 1
fi
