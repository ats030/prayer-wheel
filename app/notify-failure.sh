#!/bin/sh
# systemd ユニットが failed になったときに Discord へ通知する。
# OnFailure=notify-failure@%n.service から呼ばれる (%i に元ユニット名が入る)。
#
# 前提: 業務的な「成果物なし」は exit 3 + SuccessExitStatus=3 で success 扱いに
# してあること (~/CLAUDE.md の終了コード規約)。分けずに通知を付けると、設計どおりの
# 結果が失敗として流れてきて通知が信用されなくなる。
set -e

UNIT="$1"
[ -n "$UNIT" ] || { echo "使い方: $0 <unit名>" >&2; exit 2; }

# 秘密は ~/.env にしかない。systemd の EnvironmentFile を使うとパース差異を踏むので
# シェルで読む (値に空白やJSONが入る行があるため、必要なキーだけ取り出す)
WEBHOOK=$(sed -n 's/^DISCORD_WEBHOOK_URL=//p' "$HOME/.env" | head -1 | tr -d '"')
RESULT=$(systemctl --user show "$UNIT" -p Result --value 2>/dev/null || echo unknown)
STATUS=$(systemctl --user show "$UNIT" -p ExecMainStatus --value 2>/dev/null || echo '?')
LOG=$(journalctl --user -u "$UNIT" -n 15 --no-pager -o cat 2>/dev/null | tail -15)

TEXT=$(printf '🚨 **%s** が失敗しました (result=%s, exit=%s)\n```\n%s\n```' \
    "$UNIT" "$RESULT" "$STATUS" "$LOG")

# journal には必ず残す。Webhook 未設定でも障害の記録が消えないようにするため
printf '%s\n' "$TEXT"

[ -n "$WEBHOOK" ] || { echo "DISCORD_WEBHOOK_URL が未設定のため通知は送らない" >&2; exit 0; }

# Discord のメッセージ上限は2000文字。超えると 400 で落ちるので切り詰める
PAYLOAD=$(TEXT="$TEXT" python3 -c '
import json, os
print(json.dumps({"content": os.environ["TEXT"][:1900]}))
')
curl -sS -m 20 -H "Content-Type: application/json" -d "$PAYLOAD" "$WEBHOOK" >/dev/null \
    || echo "Discord への送信に失敗した" >&2
