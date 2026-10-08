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
npm --prefix ../cloudflare-browser-photo-probe install --ignore-scripts
python3 build.py
uv sync --offline
/home/ats030/.nvm/versions/node/v24.19.0/bin/node /tmp/cloudflare-migration-tools/node_modules/wrangler/bin/wrangler.js d1 migrations apply ikimono-note-app-local-probe --local
PATH="/home/ats030/.nvm/versions/node/v24.19.0/bin:$PWD/.venv/bin:$PATH" .venv/bin/pywrangler dev --port 8793
```

別端末で以下を実行します。

```sh
python3 check.py
python3 check_startup.py
/home/ats030/.nvm/versions/node/v24.19.0/bin/node check_browser.mjs
```

ブラウザ検証の合成fixtureは隣接probeの `generate.py` と `generate_quality.py` で生成します。
`manifest.json` にある14モジュールと60リソース、固定版vendor資産4個だけを組み立てます。静的ディレクトリの
再帰コピーはせず、隠しファイル・親パス・アプリ外の参照・余分なsrcファイル/ディレクトリを拒否します。
生成コピー、依存、DBはGit対象外、Workersのモジュール収集はsrcに限定します。
`pylock.toml` は再現用に保持します。バンドルの内容からSHA-256を計算し、実行中Workerの
healthヘッダーと照合するため、古いコピーや更新前サーバーを合格にしません。

`check_startup.py` は8794で一時workerdを起動し、secret/DB欠落時にそれぞれ
明示的な例外が出ることを確認して終了します。Node/Wranglerのパスは今回の環境の
固定ツールです。他環境ではパスを変更してください。

## 2026-10-08の結果

- ブラウザ写真経路を本体へ接続後、関連pytest33件がPASSでした。
  ローカルWorkerの58公開資産/API/D1と必須binding欠落拒否もPASSでした。
  本体モジュールのHEIC10条件、EXIF除去、PNG54画質条件、ZIP元写真SHA、
  携帯幅の撮影画面→実Workerの合成識別→写真付き記録→再識別を東京/LAで確認しました。
  以下の52資産等は接続前の起動検証結果です。
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

`IKIMONO_BROWSER_PHOTOS=1` で本体画面のHEIC/ZIP、撮影情報、画質判定、JPEG準備をブラウザへ切り替えます。
Workerは2MiB以下・長辺1600以下のJPEGヘッダーと申告情報を検証し、画像を展開しません。
申告画質は利用者が改変可能であり、検証済みの画質証明ではありません。ネイティブ版は従来経路のままです。
`IKIMONO_SYNTHETIC_AI=1` はこのローカル入口だけで識別と図鑑応答を固定し、画像展開呼出しを例外にします。
このWorkerを本番公開してはいけません。libheif再配布のソース提供条件も未完了です。
無料CPU/メモリ、本物の固定secret、OAuth登録、識別品質・実機、全データ引継ぎ、
メトリクス、上限停止、本番URLとSEO更新は未検証・未実施です。

今回の内部配信抽象化とローカル実験は利用者向け動作変更を公開していないため、
changelog対象外です。旧Cloud Runと運営者ローカル版は維持します。
本番公開時は実際の日本時間の日付でブラウザ写真処理の変更をchangelogへ追加してください。

起動前binding参照の公式例：
[Cloudflare Python/Django](https://developers.cloudflare.com/workers/languages/python/packages/django/)。
