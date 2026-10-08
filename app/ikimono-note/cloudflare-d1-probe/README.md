# D1保存経路のローカル検証

本番の `d1_store.py`、`auth.py`、`shares.py` をallowlistでコピーして、実際のPython
WorkersとローカルD1で検証します。利用者データ・OAuth秘密・外部AIは使いません。
`workers_dev: false` とダミーDB IDは公開防止のための設定です。デプロイしないでください。
依存の利用条件は `../docs/tool-license-python-workers-probe.yaml` のローカル検証条件です。

## 再現

このディレクトリで、Node.js 24と既存のuvを使います。

```sh
python3 build.py
uv sync --offline
/home/ats030/.nvm/versions/node/v24.19.0/bin/node /tmp/cloudflare-migration-tools/node_modules/wrangler/bin/wrangler.js d1 migrations apply ikimono-note-d1-local-probe --local
PATH="/home/ats030/.nvm/versions/node/v24.19.0/bin:$PWD/.venv/bin:$PATH" .venv/bin/pywrangler dev --port 8792
```

`uv sync --offline` は既存キャッシュを使います。別環境ではネットワークからの依存取得が
必要です。Wranglerのパスは今回の既存検証ツールです。コピーしたモジュール・仮想環境・
SQLiteデータ・uv.lockはGit対象外、Workersの収集範囲は `src` に限定しています。
SDKの生成する `pylock.toml` は再現用に保存します。

別端末で実行します。

```sh
python3 check.py
```

サーバーを停止して同じdevコマンドで再起動した後、保存済みデータだけを読みます。

```sh
python3 check.py --after-restart
```

再起動後のチェックはデータを作りません。初回チェックだけで再起動耐性を確認した
ことにはなりません。検証が使うユーザーと写真はすべて `synthetic-` の固定名です。
通常probeのユーザー・共有はfinallyで削除し、再起動確認用の合成レコードだけ残します。

## 2026-10-08の結果

- SQLパラメーターで文字列・日本語JSONを保持し、ユーザーのメール更新時に既存の
  作成日時とプランを維持しました。データ取得・削除と不存在も確認しました。
- 700 KiB（既存共有写真の上限）の全256バイト値を含む合成データを、明示的な
  Python bytes→JSバッファー変換でBLOB保存し、完全一致とSHA-256を確認しました。
- ページ用のSELECTは写真を読みません。写真取得はJS配列をUint8Array経由で
  Python bytesへ変換し、1バイトごとのPython整数リストを作らないようにしています。
- 共有の削除は `WHERE token=? AND owner=?` で所有者を原子的に確認します。
  他人による削除はfalseを返し、写真が残ることを確認しました。
- 空写真・上限+1バイト・未対応MIMEを既存共有と同じ例外で拒否しました。
- workerdを停止・再起動した後もユーザーと700 KiB写真が完全一致で残りました。
- ネイティブASGIのルート検証 `tests/test_d1_routes.py` 4件も成功しました。
  ログイン保存・退会・共有ページ・写真・所有者確認・公開項目の絞り込み・削除後404・
  DB binding未設定時のエラーを検証します。ネイティブのテストはSQLiteの模擬bindingで
  SQLとルート接続を検証し、Python/JS変換はこのWorkers検証で確認します。

既存authの未設定セッションキーは起動時に乱数を生成するため、Workersでは起動に
失敗しました。probeは合成固定キーをauth import前に設定します。本番entrypointでは
本物の固定キーをWorkers secretから渡す必要があります。このprobeの値は使えません。

ローカルの700 KiB往復を含む複合probeは約2.2秒、永続化約1.7秒、読取約0.3秒でした。
これはローカル経過時間であり、Workers FreeのCPU会計や本番性能を示しません。
バッファー変換とD1への大きなBLOBのシリアライズがFree CPU枠に収まるかは未検証です。

## 本番との境界

本番main.pyにはD1経路を接続しましたが、Workers entrypoint・公開・実データ移行は
未実施です。ASGI scopeにenvがないネイティブ版は従来SQLite/Firestoreを使います。
Workersのenvがある場合はDB bindingを必須とし、欠けても他の保存先へ逃がしません。
D1のクエリー例外は成功扱いせず呼出し元へ伝えます。個人の記録・設定・APIキーは
このスキーマへ入れません。公開共有とGoogleアカウントの識別情報だけを扱います。

移行対象の全データ量、Firestoreからのimport、既存tokenの保持、Google OAuth登録、
Drive/IndexedDB記録の別originへの引継ぎ、メトリクスの永続化、無料CPU/容量適合、
公開動作確認は未完了です。旧Cloud RunとFirestoreは維持しています。

公式資料：
[PythonでのD1利用](https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/)、
[D1型変換](https://developers.cloudflare.com/d1/worker-api/#type-conversion)、
[D1制限](https://developers.cloudflare.com/d1/platform/limits/)。
