#!/usr/bin/env bash
# shiseki-map を Cloud Run へ出す。既存の自己ホスト版 (systemd, port 8530) はそのまま残す。
#
#   ./deploy-cloudrun.sh            # 確認だけして、何もしない
#   ./deploy-cloudrun.sh --deploy   # 実際に出す
#
# 前提は1つ。Console でしかできないので、足りなければ止めて何をすべきか言う。
#   1. プロジェクトに請求先が紐づいていること (無料枠を使うにも要る)
#
# JALAN_A8MAT (A8.net アフィリエイトリンク用) は ~/.env から読み、Secret Manager へ
# 入れてから参照する。--set-env-vars で渡すと Console の環境変数欄に平文で並び、
# デプロイ履歴にも残るため避ける。未設定でも起動はでき、宿表示機能だけ非表示になる
# (HotelAreaService の既存の縮退動作、DESIGN.md 参照)。
#
# JALAN_API_KEY (旧 JalanService) は新規キー発行が停止済みのため渡さない。
#
# SHISEKI_SUMMARY_DISABLE=1: Cloud Run には Ollama が無いので LLM 要約は使えない。
# 史跡の各セクションは本文ブロックのみで表示され、
# 自己ホスト版（port 8530 + ローカルOllama）でのみ要約が付く。
#
# VISIT_LOG_EXEMPT_REASON: このデプロイは visit-log タグ付けを意図的に除外する。
# frontend/index.html 等には通常どおり `http://ubuntu-server-app:8526/v.js` タグを
# 残すが (自己ホスト版 port 8530 ではそのまま計測される)、Cloud Run はホーム内 LAN /
# Tailscale の外にあるため、そのホスト名にも visit-log-proxy の集計先
# (100.94.207.13:8526、Tailscale IP) にも到達できない。visit-log-proxy 自体も
# 「同一LAN上でHTML編集不可のアプリ」を127.0.0.1へ中継する設計 (~/.config/visit-log-proxy/sites.json)
# であり、GCP側からの利用は想定外。app/deploy.sh の除外運用に倣い、ここに理由を記録する
# (このスクリプトは app/deploy.sh を経由しないため自動チェックの対象外)。
set -euo pipefail

PROJECT="${SHISEKI_GCP_PROJECT:-ikimono-note-12205}"
REGION="${SHISEKI_GCP_REGION:-asia-northeast1}"
SERVICE="${SHISEKI_SERVICE:-shiseki-map}"
GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
ENV_FILE="${SHISEKI_ENV_FILE:-$HOME/.env}"
DEPLOY=0
[ "${1:-}" = "--deploy" ] && DEPLOY=1

say() { printf '%s\n' "$*"; }
fail() { printf 'できません: %s\n' "$*" >&2; exit 1; }

# ~/.env から1つ読む。行頭が KEY= のものだけ見る (export や引用符には対応しない)
env_of() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

command -v "$GCLOUD" >/dev/null 2>&1 || fail "gcloud が見つかりません ($GCLOUD)"
[ -f "$ENV_FILE" ] || fail "$ENV_FILE がありません"

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

A8MAT=$(env_of JALAN_A8MAT)
mark() { [ -n "$1" ] && printf 'あり' || printf '★無し'; }
say "  JALAN_A8MAT: $(mark "$A8MAT")$([ -n "$A8MAT" ] || printf ' (宿表示は非表示のまま公開されます)')"

if [ "$DEPLOY" != "1" ]; then
  say ""
  say "(確認のみ。実際に出すには --deploy)"
  exit 0
fi

say ""
say "■ API を有効化"
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT"

PROJECT_NUMBER=$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')
RUNTIME_SA="${SHISEKI_RUNTIME_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}"

SECRETS=""
if [ -n "$A8MAT" ]; then
  say "■ 秘密を Secret Manager へ"
  if ! "$GCLOUD" secrets describe shiseki-jalan-a8mat --project "$PROJECT" >/dev/null 2>&1; then
    "$GCLOUD" secrets create shiseki-jalan-a8mat --replication-policy=automatic --project "$PROJECT" >/dev/null
  fi
  printf '%s' "$A8MAT" | "$GCLOUD" secrets versions add shiseki-jalan-a8mat --data-file=- --project "$PROJECT" >/dev/null
  say "  shiseki-jalan-a8mat"

  say "■ 秘密の読み取りを許可 ($RUNTIME_SA)"
  "$GCLOUD" secrets add-iam-policy-binding shiseki-jalan-a8mat \
    --member="serviceAccount:$RUNTIME_SA" \
    --role="roles/secretmanager.secretAccessor" \
    --project "$PROJECT" >/dev/null
  say "  shiseki-jalan-a8mat"

  SECRETS="JALAN_A8MAT=shiseki-jalan-a8mat:latest"
fi

say ""
say "■ デプロイ"
# Cloud Run には Ollama が無いので要約生成を常時無効化する。4セクションは
# 本文ブロックのみ表示される（LLM要約は自己ホスト版でだけ使える）。
DEPLOY_ARGS=(run deploy "$SERVICE"
  --source . --project "$PROJECT" --region "$REGION"
  --service-account "$RUNTIME_SA"
  --allow-unauthenticated
  --max-instances=2
  --timeout=60
  --memory=256Mi
  --set-env-vars SHISEKI_SUMMARY_DISABLE=1)
[ -n "$SECRETS" ] && DEPLOY_ARGS+=(--set-secrets "$SECRETS")
"$GCLOUD" "${DEPLOY_ARGS[@]}"

# gcloud run deploy preserves any existing tagged-traffic split on the
# service (e.g. a staging tag). Without an explicit redirect the new
# revision can stay at 0% and production keeps serving the old one.
# --to-latest sends 100% of untagged traffic to the newest ready revision;
# --clear-tags drops leftover staging tags from the service spec. A staging
# split must therefore be applied *after* this script finishes (--set-tags),
# or it will be removed here.
"$GCLOUD" run services update-traffic "$SERVICE" \
    --project "$PROJECT" --region "$REGION" --to-latest --clear-tags

URL=$("$GCLOUD" run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
      --format='value(status.url)')

# Smoke check: confirm production actually serves the new revision with HTTP
# 200. Retry once before failing so cold starts don't cause a false alarm.
say ""
say "■ 応答確認 (smoke)"
for attempt in 1 2; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 "$URL/")
  if [ "$code" = "200" ]; then
    say "  OK (HTTP 200, try #$attempt)"
    break
  fi
  say "  HTTP $code (try #$attempt)" >&2
  if [ "$attempt" = 2 ]; then
    say "  ★smoke 失敗 — 新リビジョンが本番に乗っていない可能性があります" >&2
    exit 1
  fi
  sleep 5
done

say ""
say "■ 出ました"
say "  $URL"
