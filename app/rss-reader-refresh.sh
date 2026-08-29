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

# 前回のジョブがまだrunningなら、新規投入せずやることなし（exit 3）
running_kinds=$(curl -sS -m 10 "$BASE/api/jobs" 2>/dev/null | jq -r '.[] | select(.status == "running") | .kind' 2>/dev/null) || true
if [ -n "$running_kinds" ]; then
  echo "前回のジョブがまだ実行中: $running_kinds"
  exit 3
fi

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
    # 400（フィード未登録・上位記事は採点済み）はエラーではなく「やることがない」。
    # 呼び出し側が exit 3 に落とせるよう、障害の 1 とは別の 3 で返す。
    echo "$label: 起動せず — $(printf '%s' "$response" | jq -r '.detail // .')"
    return 3
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

# 「やることが無かった」(3) と障害 (1) を分ける。上位記事が全部採点済みの回は
# 毎時ふつうに起きるので、これを failure にすると通知が狼少年になる
# （CLAUDE.md「終了コード」。rekimeshi-bot が週17回の偽 FAILURE を出していた例）。
did_work=0

step() {
  # set -e に終了コードを奪われないよう、いったん外して受け取る
  set +e
  run_job "$@"
  code=$?
  set -e
  case "$code" in
    0) did_work=1 ;;
    3) ;;         # 対象なし。設計どおりなので続行する
    *) exit 1 ;;  # 本物の障害
  esac
}

step "フィード更新" /api/feeds/refresh-all '{}'
step "LLM採点" /api/score '{"scope":"new"}'

failing=$(curl -sS -m 10 "$BASE/health" | jq -r '.failing // 0')
if [ "$failing" -gt 0 ]; then
  echo "取得に失敗しているフィード: ${failing}件（/ の警告に一覧が出ます）"
fi

if [ "$did_work" = 0 ]; then
  echo "更新も採点も対象がありませんでした"
  exit 3
fi
exit 0
