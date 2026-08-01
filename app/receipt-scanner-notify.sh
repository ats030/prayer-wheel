#!/bin/sh
set -e

cd "$HOME"

exec /home/ats030/.local/bin/uv run python /home/ats030/pCloudDrive/Python/receipt-scanner/notify.py
