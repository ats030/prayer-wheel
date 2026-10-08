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
実Googleログイン・Drive保存・実データ移行は未検証です。
Google設定追加後のデプロイを調べる際は `--oauth` を付けます。
Google未設定の版を調べる際は付けません。bundle SHAは手元ビルドとの一致も確認します。

切戻しはCloudflareのバージョンrollbackを使います。外部アクセスを停止する場合は
この検証版だけを `workers_dev: false` にして再デプロイします。D1は削除しません。
