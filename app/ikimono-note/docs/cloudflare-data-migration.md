# Firestore移行の読み取り検証

2026年10月10日（日本時間）、課題 `ats030-paskw`。
`cloudflare/migrate_firestore.py` は旧Firestoreの `users` / `shares` をGETで取得し、
既存D1スキーマの非公開ローカルSQLiteを作る。
`cloudflare/import_d1.py` はそのスナップショットを新規・未接続のD1だけに投入し、読戻し照合する。

## 確認結果

最新の共通読み取り時点は `2026-10-09T23:41:00.363176Z`。
利用者2件・共有1件、共有写真28,200 bytes。主キー・所有者・共有token・plan・
日時・payload・写真・MIMEをそのまま保存し、各行の全列を照合した。
SQLiteのSHA256は `049f0bad77707ed3e193f4eff3065a15f98c1a1347629137c712f3b1628b3a51`。
旧FirestoreとDriveへの書き込みはない。新規の本番候補D1に取り込み、読戻し照合も完了した。

最新の実データはGit外の `/var/tmp/ikimono-cloudflare-migration-private/` に置き、
ディレクトリ0700・ファイル0600で保護する。Gitの作業ツリー内への出力は拒否する。
再起動後も保持するローカル保存先だが、OSの清掃や端末故障への保証はない。
旧Firestoreは正本として維持し、切替前にバックアップの保全方法と再取得・差分確認を確定する。
文書や課題には個人情報・写真・共有tokenを載せない。

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

読み取り段階の関連テスト16件が通過。mediumレビューのGit内保存と空ページの無限継続の指摘を修正し、
Gitディレクトリ・worktreeのGitファイル・空ページ500件の回帰テストを追加した。

## 未実施の範囲

本番候補D1は作成・インポート・読戻し照合済み。認証付きの本番候補Workerへ接続し、
共有ページ・全写真バイト/MIMEも照合した。移行中の更新差分と公開切替手順は未実施。
ブラウザIndexedDB、Driveの記録・全写真、旧共有URLの維持もこのスナップショットには含まれない。
共有tokenを保持しても旧originのURLが自動で新originへ移るわけではない。
本番公開と無料枠適合の判断は [本番化手順](cloudflare-production-rollout.md) に従う。

## 新規D1への取り込み

取り込み先は `ikimono-note-production-candidate` または合成データ専用
`ikimono-note-migration-probe` に限定する。同名DBが存在すれば書き込まず停止する。
既存検証DB・旧Firestoreは変更しない。DBを作ってもWorkerへの接続は行わない。

```sh
.venv/bin/python app/ikimono-note/cloudflare/import_d1.py \
  --snapshot /var/tmp/ikimono-cloudflare-migration-private/firestore-20261010-production-candidate.sqlite3 \
  --sha256 049f0bad77707ed3e193f4eff3065a15f98c1a1347629137c712f3b1628b3a51 \
  --name ikimono-note-production-candidate
```

作成前に入力のSHA256・ファイル権限・列・型・サイズを確認する。
SQLiteのWAL・SHM・journalがあれば停止し、ハッシュ確認したバイト列だけを
メモリ内SQLiteとして読み込む。補助ファイルや後続のファイル変更を取り込み対象にしない。
この実験は各テーブル100件、SQLite20MiB、要求20MiB、500 SQL文までとする。
写真は40,000 bytesずつのhexを使い、各SQLを100KB未満に収める。
文字列はパラメータで渡し、読戻し時は全列と全写真バイトを比較する。
[D1の上限](https://developers.cloudflare.com/d1/platform/limits/) と
[REST Query API](https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/query/)
に基づく。Free枠・利用条件の再確認は `tool-license-cloudflare-d1-candidate.yaml` にある。

作成時にDB IDだけを出力する。途中で失敗したDBは未検証として保管し、自動再試行・
削除・上書きをしない。バッチの失敗時にも中身を推測せず、未接続のまま原因を確認する。
成功表示は読戻しが一致した場合だけ出し、公開切替可能とは表示しない。
DBを既に作成した後の再確認には、`verify()` を読み取り専用で使う。
大規模データや差分更新にこの実験用処理をそのまま使わない。

### リモート照合の証拠

| 対象 | D1 ID | 結果 |
| --- | --- | --- |
| 合成データ専用 `ikimono-note-migration-probe` | `df7639bc-80fe-4412-9a8d-aaccf88f2cea` | 利用者1件・共有1件、700KiB写真の全バイトと全列が一致 |
| `ikimono-note-production-candidate` | `35c18d62-4de8-4c50-96eb-14b7d3e9e6d5` | 実利用者2件・共有1件、写真28,200 bytesと全列が一致 |

合成DBはWorker未接続。本番候補D1は認証付きWorkerへ接続した。
合成写真には0バイト・UTF8として不正なバイトを含め、
分割・連結時の写真破損を検出した。関連テストは最終21件通過。
mediumレビューの「WAL内の値はmainファイルのハッシュでは検証できない」という指摘は、
補助ファイルの拒否とハッシュ対象バイト列の読み込み、WAL回帰テストで修正した。
これはAPIでの取り込み検証であり、WorkerのCPUや利用者向け共有APIの本番動作の証明ではない。
