# アクセス制限付きCloudflare検証版

URL: https://ikimono-note-preview.ats030.workers.dev

## JavaScript入口（2026-10-09）

`front.jsonc` は同じ検証URLの入口です。`GET /api/me` だけをJavaScriptで返し、
既存Python形式のセッションCookieを検証します。Googleの3設定による利用可否・未設定理由、
セキュリティヘッダー、Basic認証・Host制限・D1必須条件を維持します。
`IKIMONO_JS_SESSION` が `1` でなければ、このAPIもPythonへ引き継ぎます。
Googleログイン、ログアウト、識別、記録などは固定のService Binding経由で既存Pythonへ渡します。
URL・要求本文・リダイレクト・複数のSet-Cookieを維持し、外部originへ秘密を転送しません。
`backend.jsonc` のPython Workerは外部URLとpreview URLを無効にし、同じ検証用D1・固定鍵・Google戻り先を使います。
新しいユーザーデータやセッション表を作りません。写真のnative transportは引き続きOFFです。

入口のbundle SHAにはPythonの意図した版も含めます。`/health` は実バックエンドのSHAと比較し、
異なる場合は503で止めます。成功時の `X-Preview-Backend-Bundle-SHA256` が実バックエンド版です。
通常応答にはruntime識別子を出さず、CPU測定の明示的マーカーがある要求だけに付けます。
JS入口の署名検証が軽くても、Pythonへ渡す要求のCPUは残ります。無料適合は要求全体で確認します。

ローカルでは以下を使います。ソースや生成物を手でビルドし直すときは先にdevを停止してください。
生成物をcustom buildで再監視しないよう、監視対象は入口・ビルドスクリプトなどのソースに限定しています。
他のPythonモジュールを変更した場合は手動再ビルドしてdevを再起動します。

```sh
python3 edge-build.py
node check_edge.mjs
python3 run_wrangler.py dev --config front.jsonc --config backend.jsonc --port 8795
python3 check.py --oauth --edge
/home/ats030/.venv/bin/python check_me.py
```

保護された検証版への反映はバックエンドを先に行います。両方が独立してビルドします。
既存の固定秘密ファイルを使い、値を表示・Git保存しません。

```sh
python3 run_wrangler.py deploy --config backend.jsonc --secrets-file /home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json
python3 run_wrangler.py deploy --config front.jsonc --secrets-file /home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json
python3 check.py https://ikimono-note-preview.ats030.workers.dev --oauth --edge
/home/ats030/.venv/bin/python check_me.py https://ikimono-note-preview.ats030.workers.dev
```

従来のPython入口へ戻す場合は `python3 build.py` の後、同じ秘密ファイルで
`python3 run_wrangler.py deploy --config wrangler.jsonc --secrets-file /home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json`
を実行し、`check.py` を `--edge` なしで確認します。非公開バックエンドは外部から使えないままです。

本番CPUは `python3 measure_edge.py --output /tmp/edge-out.json` と
`python3 measure_edge.py --signed-in --output /tmp/edge-in.json` で測ります。
後者は検証用の既存鍵で短命な合成Cookieをメモリ内に作り、`/api/me` だけに渡します。
GoogleログインやDBのユーザー作成を行いません。最初のtail確認も `/api/me` で行い、
runtime要求回数が1の場合だけ、そのruntimeの初回要求の証拠として扱います。
本物の利用者Cookieや秘密値を測定JSONへ残しません。

反映版は入口 `1aa67de5-bd31-4f88-8636-ba2d70260e2d`、非公開Pythonは
`712fe511-afdb-4ec6-95d1-533cfac7e677` です。公開URLの既存検査と実Python署名によるHTTP比較がPASSしました。
未ログインの `/api/me` はCPU0〜1msで、runtime初回要求も1msでした。
合成ログインは0〜2msでしたが、この条件のcold要求は未測定です。
このCPUは入口の値です。Python経由の要求については
`python3 measure_edge.py --backend --output /tmp/edge-backend.json` で別にtailを記録します。
別測定のPython側はhealth4〜8ms、静的ファイル3〜6msで、tail確認要求は9msでした。
応答のruntime回数は入口に属するため、Python側のcold証明には使いません。
前後の異なる測定・runtimeの差を特定処理の寄与と断定せず、全経路の無料適合も未完了です。
[本番計測記録](../docs/cloudflare-preview-production-evidence.md)に範囲と縮約証拠を保存しています。

以下は導入までの過去の検証記録と、従来Python単体での再現手順です。

全要求にBasic認証を要求します。ユーザー名は `preview`、秘密は
`~/.local/state/ikimono-cloudflare-preview/access.txt`（0600）に保存しています。
公開originから別originへ認証を転送する処理はありません。

2026-10-08に版 `f75350e9-b154-41f3-b501-f4cc982fedda` をデプロイしました。
ローカルと本番の `check.py` がPASSしました。認証なし401、不正認証401、
認証後の現行bundle hash・ページ/設定/更新履歴・対応ソースの全SHA一致、
秘密/ソース/診断404、設定変更403、過大アップロード400を確認しています。
外部AI・Google/Drive・ユーザーデータ移行・CPU会計値の検証ではありません。
CloudflareがPython-urllibの標準User-Agentを403にしたため、検証には明示的なUser-Agentを使います。
直後の404/1042は再確認で解消しました。原因は確定していません。

2026-10-08にGoogle設定を追加した版 `402d1c1d-c449-4c4a-a4ac-809f3f91d653` をデプロイしました。

`src/worker.py` は実識別APIへ接続し、合成識別/図鑑/診断を含みません。
写真解析には検証済みSDKのnative formを使い、元のFastAPI入力検証へ渡します。
繰り返された `files` を保持するSDKの `items()` とFastAPIの `getlist()` を使用します。
大きすぎる要求は、保持せずストリームを読み終えて400を返します。
D1は独立した `ikimono-note-preview` で、旧ユーザー/共有データを取り込んでいません。
起動時は固定秘密を必須確認し、D1は要求時に必須確認します。
本番アップロード検証では生きたD1ハンドルを起動時に参照できず10021になったためです。
DB欠落時は503で止め、SQLite/Firestoreへ逃がしません。

Google OAuthの設定を追加し、Basic認証の内側でも記録・設定画面にはGoogleログインを要求します。
実ログイン・Drive保存・実写真の識別/HEIC/CPU/メモリは未検証です。
既存の公開版・ローカル版・データは維持しています。検証版専用の `/changelog` を同時配信し、
公開サイトの更新履歴を公開済みとして変更していません。

## 再現と再デプロイ

### ネイティブ転送の本体組み込み（ローカル検証）

`vision.provider_payload` を3社の既存識別関数で共用し、写真なしのテンプレートから
`static/assets/provider-payload.mjs` が同じJSONを組み立てられるようにしました。
プロンプト、モデル、生成設定、写真の順序は既存の送信経路と同じです。
`IKIMONO_NATIVE_TRANSPORT=1` の検証版では、Geminiをご自身のキーで使い、Pl@ntNetを
併用しない場合に画面からこの組立て関数を呼びます。ほかのAI、お試し枠、Pl@ntNet併用は
既存の写真送信経路を使います。フラグ未設定なら全件が既存経路です。
認証を通した `/api/provider/template` が、許可モデルと撮影情報・品質を確認して
写真なしのテンプレートを返します。`/identify` で認証、モデル・キー、撮影情報・品質を
再確認し、リクエスト内だけのコールバックで `worker_transport.mjs` を呼びます。
写真JSONはPythonへ変換しません。JSが枚数、各写真2MiB、1600px以内のJPEGヘッダ、
EXIF等の禁止マーカー、MIME、プロンプト・生成設定の一致を検証します。
JPEG検証は既存Python版と同じヘッダ検査で、画素やエントロピーの完全なデコードではありません。
JSONはブラウザの標準形式に限定し、重複キーや変更された指示を拒否します。
Geminiの固定URLへ元のBlobストリームを送り、180秒タイムアウト・転送先変更拒否・
応答2MiB上限を適用します。APIキーやプロバイダーのエラー本文は診断へ返しません。
応答は既存の正規化、証拠ゲート、分類データ照合、保護種注記を通し、撮影情報と注意を返します。
実AIへの送信、再デプロイ、実CPU会計・メモリ検証は未実施です。無料枠への適合は未確定です。

`tests/test_provider_payload.py` はNodeでブラウザの組立て関数を実行し、3社それぞれの
1枚・3枚、撮影情報あり・なしをPythonの送信JSONと比較します。
テンプレートを再利用しても変更されず、不正なテンプレートや枚数を拒否することも検証します。
写真の真正性や無料枠への適合を証明するテストではありません。
転送診断の入力生成にもこの組立て関数を使い、診断専用の別実装を増やしません。
`tests/test_worker_transport.py` は合成写真1枚・3枚の転送バイト一致、設定・写真の改変拒否、
3枚とも各2MiBの場合の検証、プロバイダーの上限・異常応答を外部接続なしで確認します。
`tests/test_native_identify.py` は認証・モデル・キー・品質で転送前に止まり、正常応答が
既存の正規化と仕上げ処理を通ることを確認します。
ローカルの実Workers APIでもJPEG1枚・3枚、各2MiBの合成バッファ3枚を検証できました。
最大サイズのバッファはヘッダ検査用で、実機写真のデコード品質やメモリ安全性の証明ではありません。
未公開の内部接続のため、公開版・検証版の更新履歴は変更していません。

有効時のローカル確認は `python3 run_wrangler.py dev --port 8795 --var IKIMONO_NATIVE_TRANSPORT:1` で
起動後、`/home/ats030/.venv/bin/python check_native.py` と `node check_native_browser.mjs` を実行します。
前者は合成セッションと不正入力を使い、後者は使い捨てブラウザと合成JPEGだけを使います。
両方とも実AIを呼びません。フラグなしで起動した場合は `check_native.py --off` を使います。
有効化して公開する際は、その日の検証版更新履歴とCPU・メモリ計測を同時に記録してください。

このディレクトリで以下を実行します。既存の同一版依存を再利用します。
元アプリやprobeを変えたらdevサーバーを停止して再ビルドしてください。

```sh
python3 prepare_sources.py
python3 build.py
python3 run_wrangler.py dev --port 8795
```

別端末で `python3 check.py` を実行します。既存OAuthが期限切れなら、通常のWranglerの
`whoami` で更新後に再実行してください。新しい秘密を作る場合は実値をGitへ入れず、
固定JSONと `.dev.vars` を0600で保存してください。秘密の値を出力しないでください。

```sh
python3 run_wrangler.py deploy --secrets-file /home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json
python3 check.py https://ikimono-note-preview.ats030.workers.dev
```

対応ソースは `/vendor/photo/sources/` に同時配信します。4点の版/URL/SHAは `sources.json` に固定し、
再取得時の不一致を拒否します。GNU LGPL/GPLとMIT通知は元ライブラリと一緒に残します。
HEICモジュールは独立した通常のimportで、改変版へ置換でき、SRIによる固定はありません。
一般公開への認証解除や旧サービス停止は、この検証版の作業範囲外です。

## Google接続

入口は任意の `IKIMONO_GOOGLE_CLIENT_ID` / `IKIMONO_GOOGLE_CLIENT_SECRET` bindingを
本体へ渡せます。既存設定は秘密の値を表示せず、Git対象外の0600ファイルへ準備済みです。
Googleへの認可要求で検証版callbackは最初 `redirect_uri_mismatch` になりました。
利用者が既存OAuthクライアントに次の承認済みリダイレクトURIを追加し、
Googleのログイン画面まで進むことをログイン前のHTTP要求で確認しました。

`https://ikimono-note-preview.ats030.workers.dev/auth/callback`

旧サービスの登録は残します。有効にすると記録・設定画面はGoogleログインを要求します。
ローカルの `python3 check.py --oauth` で認可URL、PKCE/state/nonce、Secure/HttpOnly Cookie、
未ログイン画面/API拒否と不正callbackの拒否を確認しています。
確認処理はリダイレクトを追わず、Basic認証を別originへ転送しません。
利用者からGoogleログイン、Drive接続、写真記録保存と別ブラウザでの再読込の成功報告を受けています。旧データ全体の移行は未検証です。
Google設定追加後のデプロイを調べる際は `--oauth` を付けます。
Google未設定の版を調べる際は付けません。bundle SHAは手元ビルドとの一致も確認します。

切戻しはCloudflareのバージョンrollbackを使います。外部アクセスを停止する場合は
この検証版だけを `workers_dev: false` にして再デプロイします。D1は削除しません。

## 静的配信のCPU削減実験（2026-10-09 JST）

許可リストに含まれる静的ファイルを既存ASSETS bindingから配信します。
Basic認証、Host/メソッド制限、セキュリティヘッダー、APK保存名を維持します。
アプリ14モジュールは元ソースとバイト一致し、生成モデル、プロンプト、画像処理、後処理を変えていません。
ローカルと公開環境の `check.py --oauth` が成功しました。

`python3 measure_cpu.py --output /tmp/ikimono-cpu.json` は固定4経路を計測し、外部AIを呼びません。
生ログと認証情報を出力せず、失敗・欠測・版不一致は比較不適格として終了コード2にします。
静的配信の観測値は減りましたが、動的経路と初回要求は10msを超え、tailにも欠測があります。
無料枠での全体運用は未成立です。詳細と切戻し元は
[本番計測記録](../docs/cloudflare-preview-production-evidence.md)に記載しています。

## 初回要求の計測と起動時準備（2026-10-09 JST）

認証済み要求に8桁の小文字hex `X-Ikimono-CPU-Probe` がある場合だけ、応答に
`X-Preview-Isolate` と `X-Preview-Isolate-Invocation` を付けます。識別子は要求中に
生成するUUIDで、永続化しません。回数はそのPython runtimeの全fetch呼出しを数え、
未認証や早期拒否も含みます。通常・未認証・不正markerの応答には出しません。
markerは計測対象の選択用で、追加の認証情報ではありません。認証は従来のBasicです。
記録にはUUID・要求回数・CPU/応答の縮約値だけを残し、利用者や写真を識別しません。

`measure_cpu.py` は識別子欠落・不正UUID・同一runtimeの回数重複/逆順も不適格にします。
tail接続確認の再試行には異なる負のsample IDを使い、遅着した以前の試行と
新しいHTTP応答を混ぜません。「各経路の2回目以降」はwarm isolateの保証ではないため、
出力を `subsequent` と表記します。

版 `d360ac3a-1170-41d7-b606-842b76c97d98` の24要求で、測定された初回要求のCPUは
133/206/301msでした。AnyIO 4.15.1の固定版resolverでasyncio backendを起動時に読み込み、
元のFastAPIミドルウェアを起動時に組み立てる版
`851e9a73-87ad-4b96-9fd8-580ed77d8bf2` では、24要求中の初回要求は29/62/47msでした。
イベントループやtaskは起動せず、識別routeのFormData対応を設定した後でstackを作ります。
private resolverを使用するため、依存を更新する際は起動・認証・識別の検証が必要です。
本体14モジュール、モデル・プロンプト・写真処理は変更していません。

各版の24/24 tailと全HTTP200を確認し、現行版の `check.py --oauth` もPASSしました。
これは少数の別runtime間の観測で、同一ハードウェアの対比較ではありません。
初回の大きなCPU値は減りましたが、後続health11〜26ms/me10〜26msが残り、
無料枠適合は未成立です。生ログを含まない縮約JSONと解釈は本番計測記録に保存しています。
最適化前への切戻し先は `d360ac3a-1170-41d7-b606-842b76c97d98`、
今回作業全体の前の版は `cacbf9b8-5e19-4931-985b-b7794b2acd3e` です。

## 認証・ヘッダー処理の軽量化（2026-10-09 JST）

版 `6ea2d2c0-c519-4a8c-ae44-87968cfb4e83` は、ローカルで互換性を検証した
Workers専用ASGI adapterを使用します。元のセキュリティヘッダー・ログイン確認・
origin制限関数を同じ順序で呼び、TrustedHostとFastAPIの終了処理も維持します。
起動時のAnyIO準備と写真FormData対応は継続しています。

応答互換性19テスト、ローカルと公開版の `check.py --oauth`、mediumレビューを通過しました。
15配信モジュールは元ソースと一致します。公開更新履歴も同時配信しました。
完全な24件のCPU記録では後続health4〜9ms、未ログインme3〜7msでした。
最初の計測には1件のtail欠測があり、health14msも観測しています。
完全な再計測ではruntime初回呼出しを取得していないため、cold startや全体の無料適合は未確認です。
実AI・ログイン後のAPI・写真アップロード・メモリ・全件移行はこの計測の対象外です。
縮約記録と比較条件は本番計測記録を参照してください。
切戻し先は `851e9a73-87ad-4b96-9fd8-580ed77d8bf2` です。
