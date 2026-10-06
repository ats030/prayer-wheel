#!/usr/bin/env bash
# 公開版を Cloud Run へ出す。
#
#   ./deploy-cloudrun.sh            # 確認だけして、何もしない
#   ./deploy-cloudrun.sh --deploy   # 実際に出す
#
# 前提は3つ。どれも Console でしかできないので、足りなければ止めて何をすべきか言う。
#   1. プロジェクトに請求先が紐づいていること (無料枠を使うにも要る)
#   2. Firestore (ネイティブモード) が作られていること — ログイン情報の置き場
#   3. OAuth の承認済みリダイレクトURIとJS生成元に、出たあとのURLを登録すること
#      (URLは初回のデプロイで決まるので、1回出してから登録して、もう一度出す)
#
# 秘密は ~/.env から読み、Secret Manager へ入れてから参照する。--set-env-vars で
# 渡すと Console の環境変数欄に平文で並び、デプロイ履歴にも残る。
#
# 運営者の Gemini キーは**渡さない**。公開版は BYOK で、サーバー側の鍵が要るのは
# お試し枠だけ。その枠は Gemini の年齢条項と衝突して止めてある (ats030-rhfi)。
# 鍵を置いておくと、あとで枠を有効にしたときに黙って規約違反へ戻る。
set -euo pipefail

PROJECT="${IKIMONO_GCP_PROJECT:-ikimono-note-12205}"
REGION="${IKIMONO_GCP_REGION:-asia-northeast1}"
SERVICE="${IKIMONO_SERVICE:-ikimono-note}"
GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
ENV_FILE="${IKIMONO_ENV_FILE:-$HOME/.env}"
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

CLIENT_ID=$(env_of IKIMONO_GOOGLE_CLIENT_ID)
CLIENT_SECRET=$(env_of IKIMONO_GOOGLE_CLIENT_SECRET)
SESSION_SECRET=$(env_of IKIMONO_SESSION_SECRET)
# 広告と Amazon の資格情報は運営者用の設定ファイル側にある (画面から入れたもの)。
# ~/.env に無ければそちらから読む。ここを見落とすと、広告だけ空のまま出てしまう。
SETTINGS_FILE="${IKIMONO_SETTINGS_PATH:-$HOME/.config/ikimono-note/settings.json}"
settings_of() {
  [ -f "$SETTINGS_FILE" ] || return 0
  python3 - "$SETTINGS_FILE" "$1" "$2" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
print(str(data.get(sys.argv[2], {}).get(sys.argv[3], "") or ""))
PY
}
AFFILIATE_URL=$(env_of IKIMONO_AFFILIATE_URL); [ -n "$AFFILIATE_URL" ] || AFFILIATE_URL=$(settings_of affiliate url)
PARTNER_TAG=$(env_of IKIMONO_AFFILIATE_PARTNER_TAG); [ -n "$PARTNER_TAG" ] || PARTNER_TAG=$(settings_of affiliate partner_tag)
AFFILIATE_TITLE=$(env_of IKIMONO_AFFILIATE_TITLE); [ -n "$AFFILIATE_TITLE" ] || AFFILIATE_TITLE=$(settings_of affiliate title)
CREATORS_ID=$(env_of IKIMONO_AMAZON_CREATORS_ID); [ -n "$CREATORS_ID" ] || CREATORS_ID=$(settings_of api_keys amazon_creators_id)
CREATORS_SECRET=$(env_of IKIMONO_AMAZON_CREATORS_SECRET); [ -n "$CREATORS_SECRET" ] || CREATORS_SECRET=$(settings_of api_keys amazon_creators_secret)
for name in CLIENT_ID CLIENT_SECRET SESSION_SECRET; do
  [ -n "${!name}" ] || fail "$ENV_FILE に IKIMONO_GOOGLE_${name%_*}... 相当が見つかりません ($name)"
done
# 値そのものは出さない。あるか無いかだけ言えば足りる
mark() { [ -n "$1" ] && printf 'あり' || printf '★無し'; }
say "  ログイン3つ: 読めた"
say "  広告: URL $(mark "$AFFILIATE_URL") / タグ $(mark "$PARTNER_TAG")"
say "  Amazon 商品API: $(mark "$CREATORS_ID")$([ -n "$CREATORS_ID" ] || printf ' (画像付きカードは出ません)')"

say ""
say "■ 出したあとに要る登録 (URL が決まってから)"
say "  OAuth 承認済みリダイレクト URI : <サービスURL>/auth/callback"
say "  OAuth 承認済み JS 生成元       : <サービスURL>"
say "  IKIMONO_ALLOWED_HOSTS / IKIMONO_PUBLIC_ORIGIN もそのURLへ更新して出し直す"

if [ "$DEPLOY" != "1" ]; then
  say ""
  say "(確認のみ。実際に出すには --deploy)"
  exit 0
fi

PROJECT_NUMBER=$("$GCLOUD" projects describe "$PROJECT" --format='value(projectNumber)')
# 新形式のURLは決まっている (サービス名-プロジェクト番号.リージョン.run.app) ので、
# 最初のデプロイから通しておける。旧形式は status.url にしか出ないので後で足す。
NEW_HOST="$SERVICE-$PROJECT_NUMBER.$REGION.run.app"

say ""
say "■ API を有効化"
"$GCLOUD" services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com firestore.googleapis.com \
  --project "$PROJECT"

say "■ 秘密を Secret Manager へ"
put_secret() {
  local name="$1" value="$2" latest current
  [ -n "$value" ] || return 0
  if ! "$GCLOUD" secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    "$GCLOUD" secrets create "$name" --replication-policy=automatic --project "$PROJECT" >/dev/null \
      || fail "Secret を作成できません ($name)"
  fi
  # 値が同じ再デプロイでは版を増やさない。読み取り失敗時も追加せず止める。
  latest=$("$GCLOUD" secrets versions list "$name" --project "$PROJECT" \
    --limit=1 --sort-by='~createTime' --format='value(name)') \
    || fail "Secret の版を確認できません ($name)"
  if [ -n "$latest" ]; then
    # 末尾の改行も比較するため、コマンド置換の改行除去を番兵で防ぐ。
    current=$("$GCLOUD" secrets versions access "${latest##*/}" \
      --secret="$name" --project "$PROJECT" && printf '.') \
      || fail "Secret を比較できません ($name)。読み取り権限と最新版の状態を確認してください"
    current=${current%.}
    if [ "$current" = "$value" ]; then
      say "  $name (変更なし)"
      return 0
    fi
  fi
  printf '%s' "$value" | "$GCLOUD" secrets versions add "$name" --data-file=- --project "$PROJECT" >/dev/null \
    || fail "Secret の版を追加できません ($name)"
  say "  $name (更新)"
}
put_secret ikimono-google-client-secret "$CLIENT_SECRET"
put_secret ikimono-session-secret "$SESSION_SECRET"
put_secret ikimono-amazon-creators-id "$CREATORS_ID"
put_secret ikimono-amazon-creators-secret "$CREATORS_SECRET"

# 作っただけでは Cloud Run から読めない。実行サービスアカウントに、その秘密だけの
# 読み取りを与える (プロジェクト全体には広げない)。
# これが無いとビルドは通ってリビジョン作成で落ちる。実際に1周無駄にした。
RUNTIME_SA="${IKIMONO_RUNTIME_SA:-$PROJECT_NUMBER-compute@developer.gserviceaccount.com}"
say "■ 秘密の読み取りを許可 ($RUNTIME_SA)"
for name in ikimono-google-client-secret ikimono-session-secret             ikimono-amazon-creators-id ikimono-amazon-creators-secret; do
  "$GCLOUD" secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1 || continue
  "$GCLOUD" secrets add-iam-policy-binding "$name"     --member="serviceAccount:$RUNTIME_SA"     --role="roles/secretmanager.secretAccessor"     --project "$PROJECT" >/dev/null
  say "  $name"
done

SECRETS="IKIMONO_GOOGLE_CLIENT_SECRET=ikimono-google-client-secret:latest"
SECRETS="$SECRETS,IKIMONO_SESSION_SECRET=ikimono-session-secret:latest"
[ -n "$CREATORS_ID" ] && SECRETS="$SECRETS,IKIMONO_AMAZON_CREATORS_ID=ikimono-amazon-creators-id:latest"
[ -n "$CREATORS_SECRET" ] && SECRETS="$SECRETS,IKIMONO_AMAZON_CREATORS_SECRET=ikimono-amazon-creators-secret:latest"

# 公開版の姿。ディスクも常時CPUも要らない形にしてある (README の該当節)。
#
# 区切りは @ にする。ALLOWED_HOSTS は値の中にカンマが要り、既定の区切り (カンマ) の
# ままでは2つ目のホストが別の変数として解釈される。gcloud の区切り指定 ^@^ は
# **値全体の先頭**に1回だけ置くもので、途中に書くと変数名の一部になる。実際に
# ^|^IKIMONO_AFFILIATE_URL という名前の変数ができ、広告URLが渡っていなかった。
add_var() { VARS="${VARS:+$VARS@}$1=$2"; }
VARS=""
add_var IKIMONO_PUBLIC_MODE 1
add_var IKIMONO_PUBLIC_LOCAL 0          # Ollama はここに無い
add_var IKIMONO_BACKGROUND_JOBS 0       # レスポンス後に CPU が止まるため同期で返す
add_var IKIMONO_PUBLIC_TRIAL_PER_DAY 0  # 年齢条項のため無効 (ats030-rhfi)
add_var IKIMONO_PUBLIC_AFFILIATE 1      # 商用可の基盤なので広告を出す
add_var IKIMONO_FIRESTORE_PROJECT "$PROJECT"
add_var IKIMONO_GOOGLE_CLIENT_ID "$CLIENT_ID"
add_var IKIMONO_ALLOWED_HOSTS "$NEW_HOST"
add_var IKIMONO_PUBLIC_ORIGIN "https://$NEW_HOST"
[ -n "$AFFILIATE_URL" ] && add_var IKIMONO_AFFILIATE_URL "$AFFILIATE_URL"
[ -n "$AFFILIATE_TITLE" ] && add_var IKIMONO_AFFILIATE_TITLE "$AFFILIATE_TITLE"
if [ -n "$PARTNER_TAG" ]; then
  add_var IKIMONO_AFFILIATE_PARTNER_TAG "$PARTNER_TAG"
  add_var IKIMONO_AFFILIATE_ENABLED 1
  add_var IKIMONO_AFFILIATE_PRODUCT_ENABLED 1
fi

say "■ デプロイ"
"$GCLOUD" run deploy "$SERVICE" \
  --source . --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated \
  --max-instances=1 \
  --timeout=300 \
  --memory=1Gi \
  --set-env-vars "^@^$VARS" \
  --set-secrets "$SECRETS"

URL=$("$GCLOUD" run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
      --format='value(status.url)')
OLD_HOST=${URL#https://}
NEW_URL="https://$NEW_HOST"

# Route 100% of untagged traffic to the newest ready revision and clear
# leftover staging tags. The service has no OAuth- or host-dependent traffic
# split, so this is a no-op when traffic already points at latest, but it
# guards against a stale pin (e.g. a previous revision held at 100%).
"$GCLOUD" run services update-traffic "$SERVICE" \
    --project "$PROJECT" --region "$REGION" --to-latest --clear-tags

# Smoke check: ikimono-note's / 302-redirects to the login page, so accept
# any 2xx or 3xx (an HTTP response proves the new revision is serving).
# The browser-only verification below still applies for functional correctness.
say ""
say "■ 応答確認 (smoke)"
for attempt in 1 2; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 60 "$NEW_URL/")
  case "$code" in
    2*|3*)
      say "  OK (HTTP $code, try #$attempt)"
      break ;;
  esac
  say "  HTTP $code (try #$attempt)" >&2
  if [ "$attempt" = 2 ]; then
    say "  ★smoke 失敗 — 新リビジョンが本番に乗っていない可能性があります" >&2
    exit 1
  fi
  sleep 5
done

# Google は新旧2つのURLを配信する。status.url は旧形式しか返さないので、両方通す。
# 片方だけ許可していると、もう片方は TrustedHostMiddleware に 400 で弾かれる。
if [ -n "$OLD_HOST" ] && [ "$OLD_HOST" != "$NEW_HOST" ]; then
  say ""
  say "■ 旧形式のURLも通す ($OLD_HOST)"
  "$GCLOUD" run services update "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --update-env-vars "^@^IKIMONO_ALLOWED_HOSTS=$NEW_HOST,$OLD_HOST" >/dev/null
fi

say ""
say "■ 出ました"
say "  $NEW_URL"
[ "$OLD_HOST" != "$NEW_HOST" ] && say "  $URL  (旧形式。併存する)"
say ""
say "■ 残りは Console での登録 (これをしないとログインできません)"
say "  https://console.cloud.google.com/apis/credentials?project=$PROJECT"
say "  クライアント: $CLIENT_ID"
say ""
say "  承認済みのリダイレクト URI (両方):"
say "    $NEW_URL/auth/callback"
[ "$OLD_HOST" != "$NEW_HOST" ] && say "    $URL/auth/callback"
say "  承認済みの JavaScript 生成元 (両方):"
say "    $NEW_URL"
[ "$OLD_HOST" != "$NEW_HOST" ] && say "    $URL"
say ""
say "  確認はブラウザで行うこと。curl だと 302 が返るが、その行き先が同意画面か"
say "  エラー画面かは追わないと分からない (redirect_uri_mismatch を見落とした)。"
