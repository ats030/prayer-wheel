# みどころマップ / midokoro-map

祭り・温泉・史跡・特産物の4アプリを、一つのGoサーバーと共有Leaflet地図へ統合したアプリ。

## 起動と検証

```sh
go test ./...
go build -o app-server ./cmd/server
./run-local.sh
```

自己ホストは8533、Cloud RunはPORTを使用。ops/midokoro-map.serviceをユーザーsystemdへ配置し、app/deploy.sh midokoro-mapでHTMLとvisit-log登録を確認する。Cloud Runは./deploy-cloudrun.shで更新する。初回の種類はMIDOKORO_DEFAULT_KIND=onsen ./deploy-cloudrun.shなどで変更でき、後の更新でもサービス側の設定を保持する。ヘルス確認は/health（Cloud Runで予約されている/healthzは使わない）。min-instances=0、max-instances=2、リクエスト時CPU、512Mi。LAN用visit-logのホストへCloud Runから到達できないためCloud Runの集計は除外し、タグは自己ホスト用に保持する。

## 設定

- MIDOKORO_DEFAULT_KIND: shiseki（既定）/omatsuri/onsen/tokusan。初回のカテゴリ。再訪はブラウザ内の最後のカテゴリ、?kind=で直接指定できる。
- MIDOKORO_DATA_DIR: data（既定）。DBと種類別要約を読む。MIDOKORO_FRONTEND_DIRはfrontend（既定）。
- MIDOKORO_PUBLIC_ORIGIN、MIDOKORO_AFFILIATE_ORIGINS: 広告を許可するHTTPS公開先。後者はカンマ区切り。初期状態は空で通常検索。
- MIDOKORO_OMATSURI_A8MAT/MIDOKORO_ONSEN_A8MAT/MIDOKORO_SHISEKI_A8MAT: 種類別広告ID。自己ホストは旧JALAN_A8MATもフォールバックする。TOKUSAN_AMAZON_URLは広告許可時のみ使う。
- OMATSURI_SUMMARY_DISABLE/ONSEN_SUMMARY_DISABLE/SHISEKI_SUMMARY_DISABLE/TOKUSAN_SUMMARY_DISABLE=1: 新規LLM生成を停止し既存要約は配信する。Cloud Runでは全て1。

Cloud Runで広告を有効にする際はURL登録を先に済ませ、既存Secret Managerの値を--set-secretsで参照する。同じ値の新しいSecret版を作らない。自己ホストは~/.envの関連設定をrun-local.pyで読み、シェルとして実行しない。

## データ更新と戻し方

data/<kind>にDBと要約を隔離し、APIは/api/<kind>/<従来のAPIパスのapi以降>へ配置する（例 /api/onsen/onsen/）。元アプリのソース・DB・要約・収集スクリプトは保持する。更新は元アプリの収集スクリプトで出典・割当を検証し、統合版停止中にscripts/import-data.pyで取り込んで再ビルド・公開する。統合版で増えた要約を失わないよう、既存コピーがある場合は--replaceなしでは上書きしない。既存要約を別途保全してから置き換える。

cmd/warm-<kind>は統合版の種類別キャッシュへ書く。元版と統合版でデータ所有権を混ぜず、通常の閲覧は統合版のみで行う。migration-manifest.jsonは初回コピーのSHA256。

戻す場合は元アプリのsystemdサービスをenable --nowし、各元アプリのdeploy-cloudrun.sh --deployで同名の旧Cloud Runサービスを再作成する。検証後に統合版への導線を戻す。ソースとデータは削除しない。

ブラウザ検証はpython3 scripts/browser-check.py <URL>。PlaywrightとChromiumは開発環境の既存インストールを使用する。画像出力はartifacts/へ保存しgit対象外とする。


## 統合先での事前要約生成

`cmd/warm-all` は4カテゴリの全項目を対象に、概要と各節を直列生成する。
通常の公開表示やデプロイは変更しない。進行中の作業は Beads `ats030-yty61` で管理する。

旧warmを正常停止した後、`python3 scripts/import-summary-work.py` でキャッシュを移管する。
旧版と公開版のファイルは変更せず、SHA256付きのバックアップと取り込み記録を
`data/summary-work/imports` と `import-manifest.json` に保存する。
同じキーでは既存の作業用キャッシュ、統合版、旧版の順に優先する。公的資料のキャッシュは項目内の節ごとにマージする。
史跡の本文ハッシュ付き要約と、同じ原文ハッシュに結び付いた要約は再利用する。
記事名だけで保存された祭り・温泉・特産物の旧Wikipedia要約は保全し、
生成元の本文版を確認できないものを現在の原文で生成し直す。以後の本文変更でも再生成する。
特産物の公的資料の要約も、生成元の原文ハッシュが確認できる場合だけ再利用する。
移管時に原文ハッシュを推定して付けず、版の不明な旧要約は保全して生成し直す。

`sh scripts/build-summary-worker.sh` でGo 1.25のワーカーをビルドする。
`python3 scripts/run-summary-work.py --limit 1` はカテゴリごとに未完了1項目を試す。
`ops/midokoro-summary-work.service` をユーザーsystemdへ配置して有効化すると、
起動前にビルドし、特産物・温泉・祭り・史跡の順に各カテゴリ100未完了項目ずつ直列処理する。
カテゴリ間の待ちが長くなりすぎないよう、一巡ごとに確認結果を保存して再開する。
失敗を含む一巡は終了コード2で、5分後に確認済み項目を飛ばして再開する。
同じ入力の失敗は既定1時間を空け、後続の未処理項目を先に進める。`--retry-after` で変更できる。
公開前の `--recheck` はこの待ちを適用せず、全原文を確認する。
正常停止はSIGTERM、停止待ち90秒。全件確認済みになれば終了コード0で停止する。
取り込み記録がない環境ではサービスを起動しない。

作業用キャッシュは `data/summary-work/cache/<kind>`、項目別の確認結果は
`items/<kind>`、件数は `status/<kind>.json` に保存する。
排他ロックで二重起動と処理中の再取り込みを防ぐ。
これらの作業ファイルとバイナリはGit・Cloud Runビルド対象外とする。
公開サーバーが読む `data/<kind>` と競合させない。

`./summary-worker --audit` は全項目と全必須節を確認し、未完了なら終了コード2を返す。
対象一覧が空、DBの読込失敗、記事取得失敗、見出し判定の欠落、要約生成失敗は完了にしない。
確認済みの記事・節の不在は `no_source`、要約ありは `summarized`、再試行は `retry`。
入力の変更や旧形式のチェックポイントは再確認する。
前回の完了結果は `history/<kind>` に保全し、更新時の失敗で失わない。
`checked_source_hash` は今回確認した原文のハッシュで、旧要約の生成時点の原文版を表すものではない。

`--audit` はローカル成果物の構造・完了を検証する。原文の更新確認は別に
`python3 scripts/run-summary-work.py --limit 0 --recheck` で行う。
公開前にはこの全件再確認が成功し、`source-recheck.json` が complete=trueであることも必要。
完了済みでも全原文を再取得し、本文変更や取得失敗があれば再生成・未完了に戻す。
原文確認の開始・終了日時と対象一覧ハッシュを記録し、その確認時点のスナップショットとして公開する。

公開切替の条件は、全カテゴリの監査と原文再確認の成功に加え、概要を含む要約専用の描画実装、
原文が出ないことと事実項目・写真・出典・ライセンス保持のブラウザ検証、
自前サーバーとCloud Runの両方での確認である。件数だけで自動公開しない。
