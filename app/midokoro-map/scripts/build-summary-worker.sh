#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
summary_go="${MIDOKORO_GO:-$HOME/go/bin/go}"
if [ ! -x "$summary_go" ]; then summary_go=go; fi
GOTOOLCHAIN=go1.25.0 "$summary_go" build -buildvcs=false -o summary-worker ./cmd/warm-all
