#!/usr/bin/env bash
# omatsuri-map を Cloud Run へ出す。既存の自己ホスト版 (systemd, port 8527) はそのまま残す。
#
#   ./deploy-cloudrun.sh            # 確認だけして、何もしない
#   ./deploy-cloudrun.sh --deploy   # 実際に出す
#
# 前提は1つ。Console でしかできないので、足りなければ止めて何をすべきか言う。
#   1. プロジェクトに請求先が紐づいていること (無料枠を使うにも要る)
#
# アフィリエイトリンク(A8.net)は本スクリプトの時点では未実装。onsen-mapの
# HotelAreaService/JALAN_A8MATに相当する仕組みが実装され、A8.net側の提携審査が
# 通った後に、このスクリプトへSecret Manager連携を追加する(別issueで管理)。
#
# VISIT_LOG_EXEMPT_REASON: このデプロイは visit-log タグ付けを意図的に除外する。
# frontend/index.html 等には通常どおり `http://ubuntu-server-app:8526/v.js` タグを
# 残すが (自己ホスト版 port 8527 ではそのまま計測される)、Cloud Run はホーム内 LAN /
# Tailscale の外にあるため、そのホスト名にも visit-log-proxy の集計先
# (100.94.207.13:8526、Tailscale IP) にも到達できない。visit-log-proxy 自体も
# 「同一LAN上でHTML編集不可のアプリ」を127.0.0.1へ中継する設計 (~/.config/visit-log-proxy/sites.json)
# であり、GCP側からの利用は想定外。app/deploy.sh の除外運用に倣い、ここに理由を記録する
# (このスクリプトは app/deploy.sh を経由しないため自動チェックの対象外。onsen-mapの
# deploy-cloudrun.shと同一の判断根拠)。
set -euo pipefail

PROJECT="${OMATSURI_GCP_PROJECT:-ikimono-note-12205}"
REGION="${OMATSURI_GCP_REGION:-asia-northeast1}"
SERVICE="${OMATSURI_SERVICE:-omatsuri-map}"
GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
DEPLOY=0
[ "${1:-}" = "--deploy" ] && DEPLOY=1

say() { printf '%s\n' "$*"; }
fail() { printf 'できません: %s\n' "$*" >&2; exit 1; }

command -v "$GCLOUD" >/dev/null 2>&1 || fail "gcloud が見つかりません ($GCLOUD)"

say "■ 前提の確認"
billing=$("$GCLOUD" billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || echo "")
say "  請求先: ${billing:-取得できず}"
if [ "$billing" != "True" ]; then
  say ""
  say "  請求先が有効になっていません。Cloud Run は無料枠を使う場合でも必要です。"
  say "  Console → お支払い → 請求先アカウントを作る (または再開) → プロジェクトにリンク"
  say "  https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT"
  [ "$DEPLOY" = "1" ] && fail "請求先が無いので出せません"
fi

if [ "$DEPLOY" != "1" ]; then
  say ""
  say "(確認のみ。実際に出すには --deploy)"
  exit 0
fi

say ""
say "■ API を有効化"
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "$PROJECT"

PROJECT_NUMBER=$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')
RUNTIME_SA="${OMATSURI_RUNTIME_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}"

say ""
say "■ デプロイ"
"$GCLOUD" run deploy "$SERVICE" \
  --source . --project "$PROJECT" --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --max-instances=2 \
  --timeout=60 \
  --memory=256Mi

URL=$("$GCLOUD" run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
      --format='value(status.url)')

say ""
say "■ 出ました"
say "  $URL"
