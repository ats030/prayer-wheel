#!/usr/bin/env bash
# 承認済みの年表だけを静的サイトとして Cloud Run へ出す（ats030-udy41）。
# 生成アプリ本体 (systemd, 自己ホスト) はそのまま残し、公開側には生成キューを置かない。
#
#   ./deploy-cloudrun.sh            # サイトを書き出して確認だけする
#   ./deploy-cloudrun.sh --deploy   # 実際に出す
#
# 公開対象は publish.py approve で ~/data/timeline-public に入れた年表だけ。
# 書き出しは再生成できるため ~/cache に置く。
#
# VISIT_LOG_EXEMPT_REASON: このデプロイは visit-log タグ付けを意図的に除外する。
# Cloud Run はホーム内 LAN / Tailscale の外にあり、ubuntu-server-app:8526 にも
# visit-log-proxy の集計先にも到達できない。公開ページの CSP も外部スクリプトを
# 許さない。shiseki-map/deploy-cloudrun.sh と同じ扱いで、理由は ats030-udy41 に記録する
# (このスクリプトは app/deploy.sh を経由しないため自動チェックの対象外)。
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="${TIMELINE_GCP_PROJECT:-ikimono-note-12205}"
REGION="${TIMELINE_GCP_REGION:-asia-northeast1}"
SERVICE="${TIMELINE_SERVICE:-history-timeline}"
GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
BUILD_DIR="${TIMELINE_BUILD_DIR:-$HOME/cache/timeline-public-build}"
DEPLOY=0
[ "${1:-}" = "--deploy" ] && DEPLOY=1

say() { printf '%s\n' "$*"; }
fail() { printf 'できません: %s\n' "$*" >&2; exit 1; }

command -v "$GCLOUD" >/dev/null 2>&1 || fail "gcloud が見つかりません ($GCLOUD)"

say "■ サイトの書き出し"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
cp -f "$APP_DIR/cloudrun/Dockerfile" "$APP_DIR/cloudrun/nginx.conf" "$BUILD_DIR/"
(cd "$APP_DIR" && uv run --project "$HOME" python publish.py build "$BUILD_DIR/site") | sed 's/^/  /'
[ -f "$BUILD_DIR/site/index.html" ] || fail "index.html が書き出されていません"
if grep -rlq 'ubuntu-server-app\|<script' "$BUILD_DIR/site"; then
  fail "公開ページにスクリプトが含まれています"
fi

say "■ 前提の確認"
billing=$("$GCLOUD" billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || echo "")
say "  請求先: ${billing:-取得できず}"
[ "$billing" = "True" ] || fail "請求先が有効になっていません: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT"

if [ "$DEPLOY" != "1" ]; then
  say ""
  say "(確認のみ。書き出し先: $BUILD_DIR/site。実際に出すには --deploy)"
  exit 0
fi

say ""
say "■ API を有効化"
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "$PROJECT"

say ""
say "■ デプロイ"
(cd "$BUILD_DIR" && "$GCLOUD" run deploy "$SERVICE" \
  --source . --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated \
  --port=8080 \
  --max-instances=2 \
  --timeout=60 \
  --memory=128Mi)

# 既存のタグ付きトラフィック分割が残ると新リビジョンが 0% のままになるため、最新へ寄せる。
"$GCLOUD" run services update-traffic "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --to-latest --clear-tags

URL=$("$GCLOUD" run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')

say ""
say "■ 応答確認 (smoke)"
for attempt in 1 2; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 30 "$URL/" || true)
  slash=$(curl -s -o /dev/null -w '%{redirect_url}' -m 30 "$URL/showa" || true)
  case "$slash" in *:8080*) say "  ★末尾スラッシュの転送先にポートが入っています: $slash" >&2; exit 1 ;; esac
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
