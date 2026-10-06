#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
PROJECT="${MIDOKORO_GCP_PROJECT:-ikimono-note-12205}"
REGION="${MIDOKORO_GCP_REGION:-asia-northeast1}"
# Cloud Run cannot reach the LAN-only visit-log host. The tag remains for self-hosting.
# No new secret versions: initial publication uses ordinary search links.
# Preserve settings changed on the service across later deployments.
ENV_VARS="^|^MIDOKORO_PUBLIC_ORIGIN=https://midokoro-map-736831430371.asia-northeast1.run.app|OMATSURI_SUMMARY_DISABLE=1|ONSEN_SUMMARY_DISABLE=1|SHISEKI_SUMMARY_DISABLE=1|TOKUSAN_SUMMARY_DISABLE=1"
if [[ -v MIDOKORO_DEFAULT_KIND ]]; then ENV_VARS+="|MIDOKORO_DEFAULT_KIND=$MIDOKORO_DEFAULT_KIND"; fi
if [[ -v MIDOKORO_AFFILIATE_ORIGINS ]]; then ENV_VARS+="|MIDOKORO_AFFILIATE_ORIGINS=$MIDOKORO_AFFILIATE_ORIGINS"; fi
"$GCLOUD" run deploy midokoro-map --source . --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated --min-instances=0 --max-instances=2 --memory=512Mi --cpu=1 --timeout=60 \
  --update-env-vars "$ENV_VARS" --quiet
"$GCLOUD" run services update-traffic midokoro-map --project "$PROJECT" --region "$REGION" --to-latest --clear-tags --quiet
