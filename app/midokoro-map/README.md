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
