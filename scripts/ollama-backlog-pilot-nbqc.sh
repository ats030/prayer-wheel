#!/usr/bin/env bash
set -euo pipefail
cd /home/ats030
exec python3 scripts/ollama-backlog-draft.py ats030-nbqc \
  --repo app/app-portal \
  --test 'python -m pytest -q test_icons.py' \
  --one-pass-file icons.py \
  --one-pass-file check_icons.py \
  --one-pass-file test_icons.py \
  --model-timeout 300 \
  --read-only app/backlog-viewer/main.py \
  --read-only app/gathering-information/static/favicon.svg \
  --read-only kangaeru-mame/src/static/favicon.svg \
  --read-only app/image-editor/static/favicon.svg \
  --read-only image-generator/static/favicon.svg \
  --read-only app/writing/src/writing/static/favicon.svg \
  --read-only app/web-clipper/static/favicon.svg \
  --read-only app/weather-viewer/src/weather_viewer/static/favicon.svg \
  --read-only app/rss-reader/src/rss_reader/static/favicon.svg \
  --read-only app/usage-viewer/main.py \
  --read-only app/sales-viewer/main.py \
  --read-only app/tool-inventory/main.py \
  --read-only app/exam-trainer/src/exam_trainer/static/favicon.svg \
  --read-only app/dekita/favicon.svg
