#!/bin/sh
# 全フィードを更新し、続けて上位N件を Ollama で採点する。
#
# 手動の「全更新」しか無かったころは最終取得が16時間前まで伸びていた。新着が
# トップページになったので、開いた時点で最新であってほしい。採点まで済ませて
# おくのは、重要度順が LLM スコア込みで意味を持つのがそのあとだから
# （採点は1件約3.5秒なので、ブラウザを開いてから回すには遅すぎる）。
#
# ジョブは非同期なので、投げっぱなしにせず完了までポーリングする。更新の途中で
# 採点を始めると、まだ古い記事プールを対象にしてしまう。
set -eu

BASE="http://127.0.0.1:8505"
POLL_INTERVAL=5
MAX_WAIT=1800  # 39フィード＋上位50件の採点で、実測3〜5分。余裕を見て30分で打ち切る

# ジョブを起動し、完了するまで待つ。$1=ラベル, $2=パス, $3=JSONボディ
run_job() {
  label=$1
  path=$2
  body=$3

  response=$(curl -sS -m 30 -X POST -H 'Content-Type: application/json' \
    -d "$body" "$BASE$path") || {
    echo "$label: リクエストに失敗しました" >&2
    return 1
  }

  job_id=$(printf '%s' "$response" | jq -r '.job.id // empty')
  if [ -z "$job_id" ]; then
    # 400（フィード未登録・採点対象なし）はエラーではなく「やることがない」
    echo "$label: 起動せず — $(printf '%s' "$response" | jq -r '.detail // .')"
    return 0
  fi

  waited=0
  while [ "$waited" -lt "$MAX_WAIT" ]; do
    sleep "$POLL_INTERVAL"
    waited=$((waited + POLL_INTERVAL))
    # ジョブ状態はプロセス内メモリなので、再起動されると 404 になる。
    # そのときだけログの文面を変える（原因が「ジョブの失敗」ではないため）。
    job=$(curl -sS -m 30 "$BASE/api/jobs/$job_id")
    case "$(printf '%s' "$job" | jq -r '.status // "gone"')" in
      running) ;;
      finished)
        printf '%s' "$job" | jq -r --arg label "$label" \
          '"\($label): 完了 — \(.done)/\(.total) 件 \(.elapsed)秒"
           + (if .error_count > 0 then " · 失敗\(.error_count)件: \(.errors | join(", "))" else "" end)'
        return 0
        ;;
      gone)
        echo "$label: ジョブが消えました（rss-reader が再起動した可能性）" >&2
        return 1
        ;;
      *)
        echo "$label: $(printf '%s' "$job" | jq -r '.status') — $(printf '%s' "$job" | jq -r '.message')" >&2
        return 1
        ;;
    esac
  done

  echo "$label: ${MAX_WAIT}秒たっても終わらないので待機を打ち切ります" >&2
  return 1
}

# ヘルスチェック。サービスが落ちていれば採点まで進んでも意味がない
curl -sS -m 10 "$BASE/health" >/dev/null || {
  echo "rss-reader が応答しません（$BASE）" >&2
  exit 1
}

run_job "フィード更新" /api/feeds/refresh-all '{}'
run_job "LLM採点" /api/score '{"scope":"new"}'

failing=$(curl -sS -m 10 "$BASE/health" | jq -r '.failing // 0')
if [ "$failing" -gt 0 ]; then
  echo "取得に失敗しているフィード: ${failing}件（/ の警告に一覧が出ます）"
fi
exit 0
