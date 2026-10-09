# Firestore移行の読み取り検証

2026年10月10日（日本時間）、課題 `ats030-paskw`。
`cloudflare/migrate_firestore.py` は旧Firestoreの `users` / `shares` をGETで取得し、
既存D1スキーマの非公開ローカルSQLiteを作る。D1へのインポート機能はない。

## 確認結果

共通の読み取り時点は `2026-10-09T23:35:44.289379Z`。
利用者2件・共有1件、共有写真28,200 bytes。主キー・所有者・共有token・plan・
日時・payload・写真・MIMEをそのまま保存し、各行の全列を照合した。
SQLiteのSHA256は `049f0bad77707ed3e193f4eff3065a15f98c1a1347629137c712f3b1628b3a51`。
旧Firestore、Drive、Cloudflareへの書き込みはない。

実データはGit外の `/tmp/ikimono-cloudflare-migration-private/` に置き、
ディレクトリ0700・ファイル0600で保護する。Gitの作業ツリー内への出力は拒否する。
一時領域のため恒久バックアップではない。実移行前には非公開の恒久保存先と
再取得・差分確認を確定する。文書や課題には個人情報・写真・共有tokenを載せない。

## 実行と停止条件

リポジトリのルートから、既存gcloud認証と既存Python環境を使う。
出力は新規ファイルに限定し、既存ファイルを上書きしない。

```sh
.venv/bin/python app/ikimono-note/cloudflare/migrate_firestore.py \
  --output /tmp/ikimono-cloudflare-migration-private/new-snapshot.sqlite3
```

両コレクションと全ページに同じ `readTime` を渡す。
[Firestore公式List API](https://docs.cloud.google.com/firestore/docs/reference/rest/v1/projects.databases.documents/list)
の読み取り時点指定を使い、取得中の更新でページ間の時点がずれないようにする。
1ページ25件、各コレクション最大10,000件・500ページ。未知の列・型・重複主キー・
不正な写真・繰り返すページtokenは停止し、途中の成果物を削除する。
標準出力は件数・バイト数・ハッシュ等の集計のみ。認証情報や原文は出力しない。

関連テスト16件が通過。mediumレビューのGit内保存と空ページの無限継続の指摘を修正し、
Gitディレクトリ・worktreeのGitファイル・空ページ500件の回帰テストを追加した。

## 未実施の範囲

本番D1の作成・インポート・読戻し照合、移行中の更新差分と切替手順は未実施。
ブラウザIndexedDB、Driveの記録・全写真、旧共有URLの維持もこのスナップショットには含まれない。
共有tokenを保持しても旧originのURLが自動で新originへ移るわけではない。
本番公開と無料枠適合の判断は [本番化手順](cloudflare-production-rollout.md) に従う。
