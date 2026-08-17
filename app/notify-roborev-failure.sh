#!/bin/sh
# roborev のレビュージョブ自体が失敗したときに Discord へ通知する。
# .roborev.toml の [[hooks]] event = "review.failed" から呼ばれる。
#
# なぜ beads に流さないか: review.failed はコードの問題ではなくエージェント側の
# 障害 (利用枠切れ・タイムアウト・落ち) で、組み込みの beads フックはこれを P1 issue
# にする。障害と指摘を同じ待ち行列に混ぜると通知が信用されなくなる (~/CLAUDE.md の
# 終了コード規約と同じ理由)。かといって無通知にすると、失敗したコミットが
# レビューされないまま誰にも気づかれずに残る。よって別チャネルへ出す。
set -e

REPO="$1"
SHA="$2"
JOB="$3"
ERR="$4"
[ -n "$JOB" ] || { echo "使い方: $0 <repo> <sha> <job_id> [error]" >&2; exit 2; }

# 秘密は ~/.env にしかない
WEBHOOK=$(sed -n 's/^DISCORD_WEBHOOK_URL=//p' "$HOME/.env" | head -1 | tr -d '"')

TEXT=$(printf '⚠️ roborev のレビューが失敗しました (repo=%s sha=%s job=%s)\n再実行: `roborev review %s`\n```\n%s\n```' \
    "$REPO" "$SHA" "$JOB" "$SHA" "$ERR")

# ログには必ず残す。Webhook 未設定でも記録が消えないようにするため
printf '%s\n' "$TEXT"
printf '%s\t%s\t%s\t%s\n' "$(date -Is)" "$REPO" "$SHA" "$JOB" >> "$HOME/data/roborev-failed.log"

[ -n "$WEBHOOK" ] || { echo "DISCORD_WEBHOOK_URL が未設定のため通知は送らない" >&2; exit 0; }

# Discord のメッセージ上限は2000文字
PAYLOAD=$(TEXT="$TEXT" python3 -c '
import json, os
print(json.dumps({"content": os.environ["TEXT"][:1900]}))
')
curl -sS -m 20 -H "Content-Type: application/json" -d "$PAYLOAD" "$WEBHOOK" >/dev/null \
    || echo "Discord への送信に失敗した" >&2
