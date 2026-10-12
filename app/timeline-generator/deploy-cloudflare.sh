#!/usr/bin/env bash
# Public-network visit-log exemption is recorded in ats030-oehkq.
set -euo pipefail
cd "$(dirname "$0")"
build_args=()
deploy=0
for arg in "$@"; do
  case "$arg" in
    --published-snapshot) build_args+=("--published-snapshot") ;;
    --deploy) deploy=1 ;;
    *) printf 'Unknown argument: %s\n' "$arg" >&2; exit 1 ;;
  esac
done
python3 build_cloudflare.py "${build_args[@]}"
python3 -m unittest test_publish test_build_cloudflare
if [ "$deploy" = 1 ]; then
  python3 run_cloudflare.py deploy
else
  python3 run_cloudflare.py deploy --dry-run
fi
