# アクセス制限付きCloudflare検証版

URL: https://ikimono-note-preview.ats030.workers.dev

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

### 本体組み込みの準備状況

`vision.provider_payload` を3社の既存識別関数で共用し、写真なしのテンプレートから
`static/assets/provider-payload.mjs` が同じJSONを組み立てられるようにしました。
プロンプト、モデル、生成設定、写真の順序は既存の送信経路と同じです。
ブラウザ組立てはAPI呼び出しや入力検証を行わず、画面からはまだ呼び出していません。
認証済みのテンプレート取得、固定URLへのネイティブ転送、写真・品質・メタデータ検証、
Pl@ntNetと既存後処理への接続が残っています。実AI呼び出しと再デプロイは未実施です。

`tests/test_provider_payload.py` はNodeでブラウザの組立て関数を実行し、3社それぞれの
1枚・3枚、撮影情報あり・なしをPythonの送信JSONと比較します。
テンプレートを再利用しても変更されず、不正なテンプレートや枚数を拒否することも検証します。
写真の真正性や無料枠への適合を証明するテストではありません。
転送診断の入力生成にもこの組立て関数を使い、診断専用の別実装を増やしません。
未公開の内部準備のため、公開版・検証版の更新履歴は変更していません。

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
