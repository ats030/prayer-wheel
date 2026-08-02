#!/bin/sh
# ~/data の日次バックアップ。
#
# ~/data は git 追跡外・単一ディスクで、消えると戻らない (rss-reader の購読フィード・
# ブックマーク・スコア重み、receipt-scanner の記録)。コードは pCloud 上にあるのに
# データはローカルだけ、という逆転を埋めるためのもの。
#
# 設計上の判断:
#  - rclone remote へ直接送る。pCloudDrive (FUSE) 経由で書くとストールに巻き込まれる
#  - copy/sync ではなく日付つき tar.gz。ローカルが壊れた状態を同期して上書きしないため
#    (sync だと消失や破損がそのまま複製される)
#  - 秘密は入れない。~/.env はバックアップ対象外 (クラウドへ実値を出さない方針)
set -e

SRC="$HOME/data"
STAGE="$HOME/.local/var/backup"
REMOTE="pcloud:backup/ubuntu-server-app"
KEEP_DAYS=14

[ -d "$SRC" ] || { echo "バックアップ元がない: $SRC" >&2; exit 1; }

mkdir -p "$STAGE"
ARCHIVE="$STAGE/data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"

tar czf "$ARCHIVE" -C "$HOME" data
SIZE=$(du -h "$ARCHIVE" | cut -f1)

# 送信できてから古いものを消す。順序を逆にすると、送信失敗時に手元も残らない
rclone copy "$ARCHIVE" "$REMOTE/" --timeout 5m

find "$STAGE" -name 'data-*.tar.gz' -mtime "+$KEEP_DAYS" -delete
rclone delete "$REMOTE/" --include 'data-*.tar.gz' --min-age "${KEEP_DAYS}d" --timeout 5m

echo "バックアップ完了: $(basename "$ARCHIVE") ($SIZE) → $REMOTE"
