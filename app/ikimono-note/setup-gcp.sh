#!/usr/bin/env bash
# 生きものノートに要る Google Cloud の API をまとめて有効にする。
#
#   gcloud auth login          # 先に済ませておく (ブラウザでの承認が要る)
#   ./setup-gcp.sh             # 既定のプロジェクトへ
#   IKIMONO_GCP_PROJECT=xxx ./setup-gcp.sh
#
# OAuth 同意画面のスコープだけは、ここから設定できない。Console でしか触れない。
# 済んだあとに何が足りないかを表示する。
set -euo pipefail

GCLOUD="${GCLOUD:-$HOME/google-cloud-sdk/bin/gcloud}"
PROJECT="${IKIMONO_GCP_PROJECT:-}"

if ! "$GCLOUD" auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q .; then
  echo "先に認証してください:  gcloud auth login" >&2
  exit 1
fi

if [ -z "$PROJECT" ]; then
  PROJECT="$("$GCLOUD" config get-value project 2>/dev/null || true)"
fi
if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "プロジェクトを指定してください:  IKIMONO_GCP_PROJECT=<id> $0" >&2
  echo "候補:" >&2
  "$GCLOUD" projects list --format='table(projectId,name,projectNumber)' >&2
  exit 1
fi

echo "■ プロジェクト: $PROJECT"

# ドライブ保存に要る。これが無いと API 呼び出しが 403 で弾かれる
APIS="drive.googleapis.com"
# Cloud Run へ出すときに要る。いま有効にしておけば、あとで待たされない
APIS="$APIS run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com"

echo "■ API を有効にする"
for api in $APIS; do
  if "$GCLOUD" services list --enabled --project "$PROJECT" --format='value(config.name)' 2>/dev/null | grep -qx "$api"; then
    echo "  すでに有効: $api"
  else
    printf '  有効にする: %-38s' "$api"
    "$GCLOUD" services enable "$api" --project "$PROJECT" --quiet && echo "OK"
  fi
done

echo
echo "■ ここから先は Console でしか触れない"
echo "  データアクセス (スコープ) に次を足してください:"
echo "    https://www.googleapis.com/auth/drive.file"
echo "    → https://console.cloud.google.com/auth/scopes?project=$PROJECT"
echo
echo "  ログイン用の openid / email は登録済みで動いています。"
echo "  ドライブが 403 になるのは、drive.file が未登録のためです。"
