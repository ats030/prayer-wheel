# アプリ全体のWorkers起動検証

既存のmain/APIをローカルPython Workersへ載せる検証です。本番公開用の設定では
ありません。`workers_dev: false`、ダミーD1 ID、合成固定session secretを使います。
実データ・Googleの秘密・利用者キー・外部AIは使いません。依存は既存アプリと
他のprobeの固定版を再利用し、利用条件は
`../docs/tool-license-python-workers-probe.yaml` のローカル限定条件に従います。

## 再現

このディレクトリで実行します。ビルド中の不完全な組合せをwatcherが読まないよう、
再ビルド前にはdevサーバーを停止してください。

```sh
python3 build.py
uv sync --offline
/home/ats030/.nvm/versions/node/v24.19.0/bin/node /tmp/cloudflare-migration-tools/node_modules/wrangler/bin/wrangler.js d1 migrations apply ikimono-note-app-local-probe --local
PATH="/home/ats030/.nvm/versions/node/v24.19.0/bin:$PWD/.venv/bin:$PATH" .venv/bin/pywrangler dev --port 8793
```

別端末で以下を実行します。

```sh
python3 check.py
python3 check_startup.py
```

`manifest.json` にある13モジュールと54リソースだけを組み立てます。静的ディレクトリの
再帰コピーはせず、隠しファイル・親パス・アプリ外の参照・余分なsrcファイル/ディレクトリを拒否します。
生成コピー、依存、DBはGit対象外、Workersのモジュール収集はsrcに限定します。
`pylock.toml` は再現用に保持します。バンドルの内容からSHA-256を計算し、実行中Workerの
healthヘッダーと照合するため、古いコピーや更新前サーバーを合格にしません。

`check_startup.py` は8794で一時workerdを起動し、secret/DB欠落時にそれぞれ
明示的な例外が出ることを確認して終了します。Node/Wranglerのパスは今回の環境の
固定ツールです。他環境ではパスを変更してください。

## 2026-10-08の結果

- アプリ本体の起動と `/health`、公開モードでの9ページを確認しました。
- 52個の公開ページ・配信資産を確認し、HTML以外は元ファイルとバイト一致しました。
  CSS/JS/LeafletのHEADとContent-Length、CSP、nosniffも確認しました。
  ETag一致・弱いETag・複数ETag・`*`の304と、不一致時の本文も確認しました。
  APKの単一/末尾/複数Range、If-Range一致/不一致、400/416、既存HEAD拒否を確認しました。
- 公開設定のキー非公開、設定POSTの403、未許可Hostの400、docs/OpenAPI・ソース・
  設定・埋込みデータ・親パス・ディレクトリへの404、静的POSTの405を確認しました。
- 実APIを通して埋込み規制対象データのイタセンパラ指定と版を確認しました。
- 合成署名cookieとローカルD1で共有を作成し、埋込み共有HTML・PNG完全一致・
  非公開メモの除外・他人の削除拒否・本人の削除・削除後404を確認しました。
  Google OAuthの動作検証ではありません。
- 実workerdでsecret/DBそれぞれの欠落時に起動拒否を確認しました。
  launcher環境に合成secretを置いても、Worker binding欠落を通しません。
  起動検証の子プロセスへ渡す環境はHOME/PATH/TMPDIRと合成値だけに制限します。
- ネイティブの関連公開ページ/静的配信/共有等12件、規制対象データ10件、D1ルート4件が
  PASSでした。TestClientはサンドボックス内で停止したため、12件は制限外で再実行しました。

## 本番移行との境界

`bundled_resources.py` はローカル版で従来のdisk/StaticFiles/FileResponseを使い、
Workersではallowlistのbytesを使います。uvicornは直接起動時だけ読み込みます。
入口はauth/main import前に許可したbindingを環境へ渡し、公開モードと同期識別を固定し、
session secretとDBを必須にしています。

`IKIMONO_BROWSER_PHOTOS=1` はこの起動実験でHEICネイティブ登録を省くための設定です。
ブラウザHEIC/ZIP/画質処理は既存の隔離probeに留まり、本体画面には未接続です。
写真APIには既存のPillow処理が残っています。このWorkerを本番公開してはいけません。
無料CPU/メモリ、本物の固定secret、OAuth登録、識別品質・実機、全データ引継ぎ、
メトリクス、上限停止、本番URLとSEO更新は未検証・未実施です。

今回の内部配信抽象化とローカル実験は利用者向け動作変更を公開していないため、
changelog対象外です。旧Cloud Runと運営者ローカル版は維持します。

起動前binding参照の公式例：
[Cloudflare Python/Django](https://developers.cloudflare.com/workers/languages/python/packages/django/)。
