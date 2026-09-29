#!/bin/sh
# tokusan-map を Cloud Run (ikimono-note-12205, asia-northeast1) へ匿名公開でデプロイする
set -eu

GCP_PROJECT="${GCP_PROJECT:-ikimono-note-12205}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE="${SERVICE:-tokusan-map}"

# Match the local server's explicit override / enabled ikimono-note fallback.
# This contains only a public associate search URL, never API credentials.
AMAZON_TEMPLATE=$(python3 - <<'PY'
import json
import os
from pathlib import Path
if 'TOKUSAN_AMAZON_URL' in os.environ:
    value = os.environ['TOKUSAN_AMAZON_URL']
else:
    try:
        affiliate = json.loads((Path.home() / '.config/ikimono-note/settings.json').read_text()).get('affiliate', {})
        value = affiliate.get('url', '') if affiliate.get('enabled') else ''
    except (OSError, ValueError):
        value = ''
if '|' in value or '\n' in value:
    raise SystemExit('Invalid Amazon search template delimiter')
print(value)
PY
)

# TOKUSAN_SUMMARY_DISABLE=1: Cloud Run には Ollama が無いので LLM 要約は使えない。
# data/summaries.json に焼き込んだキャッシュだけを返す。
# Cloud Run は PORT=8080 を自動注入する。main.go は PORT 環境変数(デフォルト 8080)で読む。
gcloud run deploy "$SERVICE" \
  --project "$GCP_PROJECT" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated \
  --update-env-vars "^|^TOKUSAN_SUMMARY_DISABLE=1|TOKUSAN_AMAZON_URL=$AMAZON_TEMPLATE"
