#!/bin/sh
# roborev のレビュージョブ自体が失敗したときに Discord へ通知する。
# .roborev.toml の [[hooks]] event = "review.failed" から呼ばれる。
#
# なぜ beads に流さないか: review.failed はコードの問題ではなくエージェント側の
# 障害 (利用枠切れ・タイムアウト・落ち) で、組み込みの beads フックはこれを P1 issue
# にする。障害と指摘を同じ待ち行列に混ぜると通知が信用されなくなる (~/CLAUDE.md の
# 終了コード規約と同じ理由)。かといって無通知にすると、失敗したコミットが
# レビューされないまま誰にも気づかれずに残る。よって別チャネルへ出す。
#
# 引数は書式が固定な値だけを受ける (repo 名 / SHA / ジョブID)。roborev はフックの
# command を /bin/sh に渡す前にプレースホルダをシングルクォートでエスケープするので、
# 呼び出し側で更にクォートで囲んではいけない。エラー本文は長く改行を含むため
# コマンドラインには載せず、ここで roborev から引く。
#
# set -e は使わない。これは通知経路であって、途中の一手が失敗しても残りは出す。

REPO="$1"
SHA="$2"
JOB="$3"
[ -n "$JOB" ] || { echo "使い方: $0 <repo> <sha> <job_id>" >&2; exit 2; }

# 失敗理由は roborev 側から引く (コマンドラインを経由させない)。
# 失敗ジョブにはレビュー本体が無いので roborev show では取れない。error フィールドを
# 持つのは list --json のほう。フックはリポジトリの作業ディレクトリで動く。
# timeout を付ける: このフックはレビュー完了処理から同期的に呼ばれるので、自分自身の
# CLI がジョブ DB のロック待ちでブロックするとレビューパイプラインごと止まりうる。
# 取れなければ下のフォールバック文言に落ちるだけで、通知自体は飛ぶ。
ERR=$(timeout 20 roborev list --json 2>/dev/null | JOB="$JOB" python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
jobs = d if isinstance(d, list) else d.get("jobs", [])
for j in jobs:
    if str(j.get("id")) == os.environ["JOB"]:
        print((j.get("error") or "").strip()[:1200])
        break
' 2>/dev/null)
[ -n "$ERR" ] || ERR="(job $JOB の失敗理由を roborev list --json から取得できなかった)"
ERR_ONELINE=$(printf '%s' "$ERR" | tr '\n\t' '  ')

TEXT=$(printf '⚠️ roborev のレビューが失敗しました (repo=%s sha=%s job=%s)\n再実行: `roborev review %s`\n```\n%s\n```' \
    "$REPO" "$SHA" "$JOB" "$SHA" "$ERR")

# 標準出力へは必ず出す (roborev のジョブログに残る)
printf '%s\n' "$TEXT"

# 遠隔通知が先。ローカルのファイル書き込みという弱い依存で強いチャネルを止めない。
# 秘密は ~/.env にしかない
WEBHOOK=$(sed -n 's/^DISCORD_WEBHOOK_URL=//p' "$HOME/.env" 2>/dev/null | head -1 | tr -d '"')
if [ -n "$WEBHOOK" ]; then
    # Discord のメッセージ上限は2000文字
    PAYLOAD=$(TEXT="$TEXT" python3 -c '
import json, os
print(json.dumps({"content": os.environ["TEXT"][:1900]}))
' 2>/dev/null)
    if [ -n "$PAYLOAD" ]; then
        curl -sS -m 20 -H "Content-Type: application/json" -d "$PAYLOAD" "$WEBHOOK" >/dev/null \
            || echo "Discord への送信に失敗した" >&2
    fi
else
    echo "DISCORD_WEBHOOK_URL が未設定のため通知は送らない" >&2
fi

# 消えない記録には理由も残す。Discord が落ちていた期間を後から追えるようにするため。
mkdir -p "$HOME/data" 2>/dev/null || true
printf '%s\t%s\t%s\t%s\t%s\n' "$(date -Is)" "$REPO" "$SHA" "$JOB" "$ERR_ONELINE" \
    >> "$HOME/data/roborev-failed.log" 2>/dev/null || echo "ログ追記に失敗した" >&2

exit 0
