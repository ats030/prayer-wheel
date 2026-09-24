#!/bin/sh
# tokusan-map を Cloud Run (ikimono-note-12205, asia-northeast1) へ匿名公開でデプロイする
set -eu

GCP_PROJECT="${GCP_PROJECT:-ikimono-note-12205}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE="${SERVICE:-tokusan-map}"

# Cloud Run は PORT=8080 を自動注入する。main.go は PORT 環境変数(デフォルト 8080)で読む。
gcloud run deploy "$SERVICE" \
  --project "$GCP_PROJECT" \
  --region "$REGION" \
  --source . \
  --allow-unauthenticated
