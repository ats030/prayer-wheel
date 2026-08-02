#!/bin/sh
# ローカルチェックアウトからサービスを更新する。
#
#   app/deploy.sh <サービス名>
#
# 対象は $HOME/app/<サービス名> に clone してあるリポジトリ。編集は pCloudDrive 側の
# 作業コピーで行い、そこで commit & push してからこれを実行して取り込む。
#
# なぜローカルに置くか: pCloudDrive は FUSE のクラウド同期で、ストールすると稼働中の
# プロセスがページフォルトでハングまたは落ちる。起動後もコードやライブラリに触るため、
# 「起動さえすれば安全」ではない (ats030-e5z7)。
#
# ポートは systemd ユニットの Description "(port NNNN)" から拾う。書式が違う場合は
# 第2引数で渡す。ポートが取れないサービスは is-active だけ確認する。
set -e

NAME="$1"
[ -n "$NAME" ] || { echo "使い方: $0 <サービス名> [ポート]" >&2; exit 2; }

CHECKOUT="$HOME/app/$NAME"
UNIT="$NAME.service"

[ -d "$CHECKOUT/.git" ] || { echo "ローカルチェックアウトがない: $CHECKOUT" >&2; exit 1; }

echo "更新中: $CHECKOUT"
git -C "$CHECKOUT" pull --ff-only

echo "再起動: $UNIT"
systemctl --user restart "$UNIT"

PORT="$2"
if [ -z "$PORT" ]; then
    PORT=$(systemctl --user show "$UNIT" -p Description --value | sed -n 's/.*port \([0-9]\{4,5\}\).*/\1/p')
fi

if [ -z "$PORT" ]; then
    # 常駐しないバッチ (Type=oneshot) は restart 直後に inactive でも正常
    sleep 2
    STATE=$(systemctl --user show "$UNIT" -p ActiveState --value)
    RESULT=$(systemctl --user show "$UNIT" -p Result --value)
    echo "ポート不明のため状態のみ確認: ActiveState=$STATE Result=$RESULT"
    [ "$RESULT" = "success" ] || { echo "起動に失敗している" >&2; exit 1; }
    exit 0
fi

i=0
while [ "$i" -lt 30 ]; do
    # 503 は「起動しているが依存先が落ちている」= サービス自体は生きている
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/" 2>/dev/null || true)
    case "$code" in
        2*|3*|401|403|503) echo "応答を確認 (HTTP $code, port $PORT)"; exit 0 ;;
    esac
    i=$((i + 1))
    sleep 1
done

echo "30秒待っても port $PORT が応答しない" >&2
systemctl --user status "$UNIT" --no-pager | head -12 >&2
exit 1
