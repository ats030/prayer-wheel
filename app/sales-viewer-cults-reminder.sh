#!/bin/sh
cd /home/ats030/app/sales-viewer || exit 1
exec /home/ats030/.local/bin/uv run python cults_reminder.py
