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

## 本体の写真転送CPUを切り分ける実験

既存の画像処理をブラウザへ移しても、FastAPIのmultipart解析とD1のBLOB転送には
大きな負荷が残りました。`IKIMONO_SYNTHETIC_AI=1` と `IKIMONO_PROFILE_IO=1` を
両方設定し、URLとHostがlocalhost/127.0.0.1の場合だけ、`/probe/profile/` を使えます。
本番入口には移植していません。flagがOFFなら診断入口は403です。

起動後に以下を実行します。合成入力と生の計測結果はGit対象外です。

```sh
/home/ats030/.venv/bin/python prepare_profile.py
python3 check_profile.py
/home/ats030/.nvm/versions/node/v24.19.0/bin/node profile.mjs > profile-fixtures/results.jsonl
```

他のWorkerを同時に起動しないでください。既存Playwrightのwsを利用して9229の
V8 Inspectorに接続し、1000μs間隔でwarm後3回ずつサンプリングします。
`(idle)`/`(root)`を除いたサンプル時間を集計します。Inspectorやローカル環境の負荷を
含む近似値で、本番CPU会計ではありません。起動時のcold CPU/メモリも測りません。
healthのbundle hashと現在のソースを照合し、古いWorkerは拒否します。

`/tmp/cloudflare-migration-tools` が消えている環境では、既存キャッシュの同一版
Wrangler 4.148.0を使えます。`check_startup.py` にはその `wrangler.js` の絶対パスを
`IKIMONO_PROBE_WRANGLER` で渡してください。今回の再検証では
`/home/ats030/.npm/_npx/32026684e21afda6/node_modules/wrangler/bin/wrangler.js` を使いました。
Inspector付き起動では `dev --port 8793 --inspector-port 9229` を指定します。

2026-10-08、bundle `9b3df268c92d20fe0cbddc17642c8da3cedbfff03cea407e4de28ba387a41bf2`
で観測したactive sampled時間の中央値です。入力はseed=3の合成1600×1600 JPEG
1,997,593 bytesと、固定合成700KiBデータです。画質の申告値は合成で、識別・図鑑も
合成応答です。実AI呼出し、送信時のbase64/JSON組立ての負荷は含みません。

| 経路 | 中央値(ms) |
| --- | ---: |
| ASGI health / ネイティブhealth | 14.0 / 5.5 |
| 設定取得 / HTML | 12.0 / 11.9 |
| HEICデコーダー資産配信 | 56.3 |
| 既存識別API・JPEG1枚 / 3枚 | 1192.7 / 3585.3 |
| 同じ識別API・ネイティブform解析・1枚 / 3枚 | 21.5 / 46.7 |
| 解析とSHAだけ・1枚 / 3枚 | 17.2 / 34.7 |
| 本体共有API・700KiB保存 / 取得 | 2263.9 / 290.7 |
| D1 BLOBだけ・700KiB保存 / 取得 | 1711.1 / 288.6 |
| D1 hex転送だけ・700KiB保存 / 取得 | 7.6 / 23.6 |

ネイティブform解析の比較は、元のFastAPI route handlerへrequest単位のFormDataを渡し、
同じPydantic入力検証・モデル/キー/写真ヘッダー/画質申告検証を通します。
通常の`/identify`は既存multipart解析のままです。ネイティブ解析後に作るbodyなし要求へ
元のヘッダーを引き継ぐ方法は、この固定版SDKでの隔離比較に限定しています。
APIの写真SHA・撮影日/GPS、不正申告422、欠落申告400、MIME415、枚数/暗さ拒否、
不許可Host403を`check_profile.py`で確認しました。`check_startup.py`はflag OFFも確認します。

D1比較はSQLの`unhex(?)`で保存し`hex(photo)`で取得します。DB内は既存BLOBのままで、
新しい保存形式ではありません。固定token/ownerの合成行だけを使い、SHAと長さを照合し、
finallyで削除します。hexは転送サイズが2倍になるため、700KiBより大きな写真へ無条件に
適用する方法ではありません。未知のSQLや利用者tokenを受け取りません。

上表の旧D1 writeはwarm後のUPSERT更新を測っていました。共有の新規作成と比較するには
不十分なので、現在のコードは計測外で固定合成行を削除し、各回をINSERTに統一しています。
共有ページ/写真取得とD1操作のwall値も、現在はInspectorのstop処理より前に確定します。

## Gemini送信データの組立て検証

`native-gemini-payload` は既存 `vision.identify_gemini` の関数を複製し、その関数だけの
HTTPX参照を合成postへ差し替えます。グローバル関数や他の要求は変更しません。
本体のbase64化・prompt/schema生成・HTTPX RequestのJSONシリアライズ・合成応答の
normalizeを実行します。モデル/キーは固定合成値で、HTTP転送や外部AIは呼びません。
測定にはnative form解析、写真/送信JSONのSHA256、応答生成も含みます。
実AI通信全体やbase64化だけのCPUを測るものではありません。

別の `native-gemini-payload-checked` で送信JSONを復元し、1枚/3枚すべての原本との
完全一致を確認します。`check_profile.py` は測定入口と検証入口の送信JSON SHA256・
長さ・写真SHA256が一致することを確認します。復元検証は計測入口に含めません。
どちらの入口も既存のlocal Host・合成flag・枚数/サイズ制限を通ります。
`profile.mjs` の出力はwarm後各3回、全60サンプルです。

2026-10-08の修正後再測定（bundle
`1413cd9efe744681492b0c04e3da2652e2a5272abb02195281ce1b34d536a6e9`）では、
上と同じ合成JPEG/700KiB入力で次のactive sampled中央値を観測しました。
測定中は他のWorker/起動拒否検証を実行していません。

| 経路 | 中央値(ms) |
| --- | ---: |
| 同じ識別API・native form・1枚 / 3枚 | 19.4 / 41.8 |
| Gemini送信JSON組立て経路・1枚 / 3枚 | 50.2 / 144.2 |
| D1 BLOB新規INSERT / 取得 | 1636.4 / 283.5 |
| D1 hex新規INSERT / 取得 | 16.1 / 24.9 |

全60サンプルで同じbundle hash、写真の全SHA256、D1読取の全長/SHA256を確認しました。
58公開資産/API/D1と既存/native識別の1枚/3枚、Gemini JSON復元の完全一致もPASSです。
無料運用の成立を示す結果ではなく、multipart改善後にも送信JSON組立てと共有取得に
負荷が残る証拠です。次に本番CPU計測と、Python/JS境界の転送・配信の負荷削減を
検証する必要があります。実AI品質、メモリ、OAuth、実データ移行は未検証です。

この実験は負荷原因と改善余地を示しますが、無料運用の合格判定ではありません。
[Workers FreeのCPU上限10ms](https://developers.cloudflare.com/workers/platform/limits/)と
[D1の文字列/BLOB/行上限2,000,000 bytes](https://developers.cloudflare.com/d1/platform/limits/)は
2026-10-08に確認しました。写真3枚・読取・ASGI/静的配信の残る負荷、実AIへの送信、
本番CPU/メモリ/上限停止の検証が必要です。有料化や機能削減は行いません。
