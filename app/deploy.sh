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
BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT

register_visit_log_site() {
    site_url="http://ubuntu-server-app:$PORT/"
    payload=$(printf '{"name":"%s","url":"%s","note":"app/deploy.sh auto"}' \
        "$NAME" "$site_url")
    if ! curl -fsS -H 'Content-Type: application/json' \
        --data "$payload" http://ubuntu-server-app:8526/api/sites >/dev/null; then
        echo "visit-log へのサイト登録に失敗: $NAME" >&2
        return 1
    fi
    echo "visit-log 登録を確認: $NAME ($site_url)"
}

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

# 認証情報を扱うサービスは Tailnet IP にだけ bind し localhost では応答しない
# (ats030-c77a)。localhost で応答がなければ Tailnet IP も試す。
TAILNET_IP=$(tailscale ip -4 2>/dev/null | head -n 1 || true)

i=0
while [ "$i" -lt 30 ]; do
    # 503 は「起動しているが依存先が落ちている」= サービス自体は生きている
    code=$(curl -s -L --max-redirs 5 -o "$BODY_FILE" -w '%{http_code}' \
        "http://localhost:$PORT/" 2>/dev/null || true)
    if [ "$code" = "000" ] && [ -n "$TAILNET_IP" ]; then
        code=$(curl -s -L --max-redirs 5 -o "$BODY_FILE" -w '%{http_code}' \
            "http://$TAILNET_IP:$PORT/" 2>/dev/null || true)
    fi
    case "$code" in
        2*)
            if grep -Eiq '<!doctype html|<html([ >]|$)' "$BODY_FILE"; then
                if [ -n "${VISIT_LOG_EXEMPT_REASON:-}" ]; then
                    echo "visit-log 除外: $VISIT_LOG_EXEMPT_REASON"
                elif ! grep -Fq 'http://ubuntu-server-app:8526/v.js' "$BODY_FILE" ||
                     ! grep -Fq "data-site=\"$NAME\"" "$BODY_FILE"; then
                    echo "visit-log タグがない: $NAME (port $PORT)" >&2
                    echo "追加: <script src=\"http://ubuntu-server-app:8526/v.js\" data-site=\"$NAME\" defer></script>" >&2
                    echo "例外にする場合: VISIT_LOG_EXEMPT_REASON='理由' app/deploy.sh $NAME" >&2
                    exit 1
                fi
                register_visit_log_site
            fi
            echo "応答を確認 (HTTP $code, port $PORT)"
            exit 0
            ;;
        3*|401|403|503) echo "応答を確認 (HTTP $code, port $PORT)"; exit 0 ;;
    esac
    i=$((i + 1))
    sleep 1
done

echo "30秒待っても port $PORT が応答しない" >&2
systemctl --user status "$UNIT" --no-pager | head -12 >&2
exit 1
