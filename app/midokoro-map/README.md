# みどころマップ / midokoro-map

祭り・温泉・史跡・特産物の4アプリを、一つのGoサーバーと共有Leaflet地図へ統合したアプリ。

Cloudflareへの公開移行と更新・検証・復旧手順は [docs/cloudflare-migration.md](docs/cloudflare-migration.md) を参照。

## 起動と検証

```sh
go test ./...
go build -o app-server ./cmd/server
./run-local.sh
```

自己ホストは8533、Cloud RunはPORTを使用。ops/midokoro-map.serviceをユーザーsystemdへ配置し、app/deploy.sh midokoro-mapでHTMLとvisit-log登録を確認する。Cloud Runは./deploy-cloudrun.shで更新する。初回の種類はMIDOKORO_DEFAULT_KIND=onsen ./deploy-cloudrun.shなどで変更でき、後の更新でもサービス側の設定を保持する。ヘルス確認は/health（Cloud Runで予約されている/healthzは使わない）。min-instances=0、max-instances=2、リクエスト時CPU、512Mi。LAN用visit-logのホストへCloud Runから到達できないためCloud Runの集計は除外し、タグは自己ホスト用に保持する。

## 設定

- MIDOKORO_DEFAULT_KIND: shiseki（既定）/omatsuri/onsen/tokusan/geo。初回のカテゴリ。再訪はブラウザ内の最後のカテゴリ、?kind=で直接指定できる。
- MIDOKORO_DATA_DIR: data（既定）。DBと種類別要約を読む。MIDOKORO_FRONTEND_DIRはfrontend（既定）。
- MIDOKORO_PUBLIC_ORIGIN、MIDOKORO_AFFILIATE_ORIGINS: 広告を許可するHTTPS公開先。後者はカンマ区切り。初期状態は空で通常検索。
- MIDOKORO_OMATSURI_A8MAT/MIDOKORO_ONSEN_A8MAT/MIDOKORO_SHISEKI_A8MAT: 種類別広告ID。自己ホストは旧JALAN_A8MATもフォールバックする。TOKUSAN_AMAZON_URLは広告許可時のみ使う。
- OMATSURI_SUMMARY_DISABLE/ONSEN_SUMMARY_DISABLE/SHISEKI_SUMMARY_DISABLE/TOKUSAN_SUMMARY_DISABLE=1: 新規LLM生成を停止し既存要約は配信する。Cloud Runでは全て1。

Cloud Runで広告を有効にする際はURL登録を先に済ませ、既存Secret Managerの値を--set-secretsで参照する。同じ値の新しいSecret版を作らない。自己ホストは~/.envの関連設定をrun-local.pyで読み、シェルとして実行しない。

## データ更新と戻し方

data/<kind>にDBと要約を隔離し、APIは/api/<kind>/<従来のAPIパスのapi以降>へ配置する（例 /api/onsen/onsen/）。元アプリのソース・DB・要約・収集スクリプトは保持する。更新は元アプリの収集スクリプトで出典・割当を検証し、統合版停止中にscripts/import-data.pyで取り込んで再ビルド・公開する。統合版で増えた要約を失わないよう、既存コピーがある場合は--replaceなしでは上書きしない。既存要約を別途保全してから置き換える。

「地形・地質」タブ（`?kind=geo`）でジオパーク範囲と地質鉱物の天然記念物を表示する。名称・地域・種別で絞り込み、一覧と地図から出典付きの情報を開ける。他4カテゴリには地質レイヤーを重ねない。正本は app/geo-map/data/geo.db。import-data.py --kind geo --replace が明示的に data/geo に取り込み、scripts/build-geo-layer.py が frontend/geo/geoparks.json（簡略化した範囲と各種別の範囲内件数）と frontend/geo/geosites.json（地質鉱物の天然記念物）を生成する。史跡タブに同じ文化庁 ID の点、または同名で1km以内の点がある天然記念物は properties.shiseki にその site_id を持ち、従来の重ね合わせ表示では史跡タブで隠していた（対応一覧は meta.shown_by_shiseki）。独立した地形・地質タブではこれらも表示する。点データを取り込み直したら build-geo-layer.py も再実行する。古いままだと build-cloudflare.py が停止する。

cmd/warm-<kind>は統合版の種類別キャッシュへ書く。元版と統合版でデータ所有権を混ぜず、通常の閲覧は統合版のみで行う。migration-manifest.jsonは初回コピーのSHA256。

戻す場合は元アプリのsystemdサービスをenable --nowし、各元アプリのdeploy-cloudrun.sh --deployで同名の旧Cloud Runサービスを再作成する。検証後に統合版への導線を戻す。ソースとデータは削除しない。

ブラウザ検証はpython3 scripts/browser-check.py <URL>。PlaywrightとChromiumは開発環境の既存インストールを使用する。画像出力はartifacts/へ保存しgit対象外とする。

## 文化のつながりをたどる実験

`/stories/arita-porcelain` は有田の5地点を原料・焼成・町並み・信仰・仕事の記録からたどるテーマページ。
HTML本文を正本にして、地点と関係をJavaScriptで地図へ反映する。
関係の選択と選択地点をURLで復元し、共有URLには `from=shared` を付ける。
資料・座標の根拠と判断は `docs/arita-story.md`。自動生成した関係や既存DBの変更は含まない。

`python3 scripts/browser-story-check.py <URL>` はPC/スマホ、URL復元、共有の代替、地図失敗、JSなし、Do Not Trackと操作計測を検証する。
操作計測は同一オリジンの空POST `/api/story-events/arita-porcelain/<event>` で既存のリクエストログと標準ログに記録する。
イベントは固定の8種類、各ページ読込につき各種類1回。アプリは識別子・本文・参照元を記録せず、DNT時は送信しない。
Cloud Runの既存リクエストログは通常のプラットフォーム項目を保持する。ログの保存期間と権限は変更しない。
自己ホストではjournalの `story_event` 行を、公開版は既存visit-logのCloud Runパス集計を使える。
イベント送信はブラウザやネットワークで欠測し、ログにはbot/人工リクエストも入り得るため、PV・ユニーク人数・共有完了・現地訪問として扱わない。
実験の判断基準とロールバックは同文書に記録。SNS投稿や外部リンク依頼はこの実装に含まない。


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
バックグラウンド処理は `SUMMARY_REQUEST_TIMEOUT=15m` でローカルモデルの待ち行列を待つ。
公開サーバーの既定60秒は変更しない。起動時のビルドはVCS情報の付与を省き、ホーム全体のGit走査を避ける。
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
4カテゴリの対象一覧は公開APIと同じDBから読み、別途書き出したJSONとのずれを避ける。
確認済みの記事・節の不在は `no_source`、要約ありは `summarized`、再試行は `retry`。
入力の変更や旧形式のチェックポイントは再確認する。
前回の完了結果は `history/<kind>` に保全し、更新時の失敗で失わない。
`checked_source_hash` は今回確認した原文のハッシュで、旧要約の生成時点の原文版を表すものではない。

`--audit` はローカル成果物の構造・完了を検証する。原文の更新確認は別に
`python3 scripts/run-summary-work.py --limit 0 --recheck` で行う。
公開前にはこの全件再確認が成功し、`source-recheck.json` が complete=trueであることも必要。
完了済みでも全原文を再取得し、本文変更や取得失敗があれば再生成・未完了に戻す。
原文確認の開始・終了日時と対象一覧ハッシュを記録し、その確認時点のスナップショットとして公開する。
再確認の開始時に前回の成功記録を無効化するため、途中失敗で古い成功を使い回さない。

再確認の成功から24時間以内に
`python3 scripts/run-summary-work.py --export data/published-summaries.json` を実行する。
対象一覧と各項目の入力が同じで、全項目が成功した再確認の期間内に検証されている場合だけ書き出す。
生成元のDB・JSONとこの成果物を同じ版で配布し、`MIDOKORO_SUMMARIES_ONLY=1` で公開サーバーを起動する。
成果物がない、必須節が欠ける、再試行が残る場合は要約専用モードの起動を拒否する。
書き出し時と起動時に4つのDBの内容ハッシュと全IDを照合し、対象データの更新で古い成果物を使わない。
内容ハッシュは読取トランザクション内のスキーマと全行から計算し、WALに記録された更新も含める。
概要を含む説明は専用APIの要約・構造化項目だけを描画し、確認済みの情報なしは節を隠す。
読込失敗では原文に戻さず失敗を表示する。基本情報・写真・出典は既存の処理を維持する。
切替前はこの環境変数を設定せず、従来表示を維持する。
切戻しは環境変数を解除して直前の成果物・アプリ版で再起動する。旧キャッシュは削除しない。

`python3 scripts/browser-summary-check.py <検証用URL>` は要約専用APIをテスト用データに置き換え、
4カテゴリの要約表示、原文展開の不在、確認済み情報なし、基本情報と出典ライセンスを確認する。
実データの公開確認を代替するものではない。

公開切替の条件は、全カテゴリの監査と原文再確認の成功に加え、概要を含む要約専用の描画実装、
原文が出ないことと事実項目・写真・出典・ライセンス保持のブラウザ検証、
自前サーバーとCloud Runの両方での確認である。件数だけで自動公開しない。

文化の地図は `/stories` から有田・草津・川越を選べます。追加テーマの根拠と検証は [docs/additional-stories.md](docs/additional-stories.md) に記録しています。

Ollamaで同じ形式の記事下書きを作れます。確認済みの資料パケットから `python3 scripts/generate-story.py --packet docs/story-packets/kusatsu-yumomi.json --output data/story-work/kusatsu-draft` で本文・出典確認資料・探索プレビューを出力します。手順と検証範囲は [docs/ollama-stories.md](docs/ollama-stories.md) を参照してください。

## ジオパーク境界とビルド用DB

ジオパークの件数は所属判定用の約50m境界で数え、地図には正本で作成した約500mの表示用輪郭を使います。表示輪郭はShapelyでトポロジーを維持して簡略化します。境界付近ではクリックできる表示範囲と集計範囲が異なるため、詳細パネルにその差を明記します。所属判定を粗い表示範囲へ合わせません。

`data/geo/geo.db` は統合版のビルドスナップショットです。正本DBの更新と統合版の公開を分け、Cloudflareビルドが公開JSONの鮮度を検査するために保持します。サーバーはこのDBを読まないため `.dockerignore` でDockerのビルド入力から除外します。4カテゴリのデータと `published-summaries.json` など既存の起動用データは維持します。通常のデータ取込はgeoを除外し、ジオデータを更新する際だけ `scripts/import-data.py --kind geo --replace` と `scripts/build-geo-layer.py` を実行します。

## 国立公園の更新

地形・地質タブで「国立公園」を選ぶと、公園区域を青い破線で表示します。名称・都道府県で検索でき、一覧または範囲から公式情報・指定・面積・区域の出典とデータ年度を開けます。国立公園の範囲は環境省EADASの公園区域を結合・簡略化したもので、ジオパークの構成自治体範囲とは区別します。重なる範囲をクリックすると詳細パネルの「この位置で重なる範囲」から表示対象を選べます。

`app/geo-map` で `uv run python scripts/nationalparks.py`（再取得は `--refresh`）を実行し、統合版の `scripts/import-data.py --kind geo --replace` と `scripts/build-geo-layer.py` で取り込みます。`frontend/geo/nationalparks.json` もCloudflareビルドの鮮度検査対象です。戻す場合は同じ版のgeo.db・migration-manifest.json・3つの公開GeoJSONを戻し、対応するフロントエンドと一緒に更新します。
