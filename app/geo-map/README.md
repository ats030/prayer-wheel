# geo-map

midokoro-map が使う地形・地質データの正本です。サービスは持たず、`data/geo.db` を生成して git で管理します。

## ジオパーク

```bash
uv run python scripts/geoparks.py            # キャッシュから再生成
uv run python scripts/geoparks.py --refresh  # geopark.jp を再取得してから再生成
uv run pytest
```

- 地域一覧と構成自治体: [日本ジオパークネットワーク](https://geopark.jp/geopark/) の一覧ページと各地域ページ。HTML コメントで外された地域は撤退済みとして除きます。
- 範囲: [国土数値情報 行政区域データ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html) N03-20260101 の市区町村ポリゴンを結合し、約50m (0.0005度) で簡略化します。表示用には同じ範囲をShapelyの `preserve_topology=True` で約500m (0.005度) に簡略化し、`display_geometry` に保持します。表示用では0.005度四方より面積の小さい島を省きます。小島だけの地域でも面積最大のポリゴンを残します。所属判定用の範囲からは島を省きません。
- 「山口市（阿東地域）」のように一部だけが含まれる自治体は `partial` として記録し、範囲には含めません。
- 一覧ページの自治体数と地域ページの構成自治体数を照合します。食い違いは地域ページを正とし、既知のものは `KNOWN_COUNT_GAPS` に理由を書きます。
- 取得は1秒間隔です。ページは `~/cache/geo-map/pages`（取得日は `meta.json`）、N03 は `~/cache/geo-map/n03` に置きます。
- 構成自治体を読めない地域、未解決の自治体、範囲なしの地域、自治体数の食い違いがあると終了コード1で止まります。

## 天然記念物（地質鉱物）

```bash
uv run python scripts/geosites.py            # キャッシュから再生成
uv run python scripts/geosites.py --refresh  # CSV と全詳細ページを再取得してから再生成
```

- 一覧: [国指定文化財等データベース](https://kunishitei.bunka.go.jp/bsys/index) の天然記念物・特別天然記念物 CSV（`~/cache/geo-map/tennen`）。
- CSV に指定基準がないため、詳細ページ `https://kunishitei.bunka.go.jp/heritage/detail/401/{管理対象ID}` を1秒間隔で取得します（`~/cache/geo-map/tennen-detail`、ステータスと最終 URL は `tennen/meta.json`）。管理対象 ID のゼロ詰めは削りません。削るとエラーページへ転送されます。
- 指定基準を地質鉱物（一）〜（十二）の語句全体で照合します。「岩石」「洞穴」だけでは判定しません。名勝の「五．岩石、洞穴」や植物の（九）と区別するためです。
- 分類: `geo`（地質鉱物のみ）、`geo+bio`（動植物の基準も含む）、`bio`、`other`（名勝の基準だけなど）、`unknown`（指定基準が空）。`geosite` には `geo` と `geo+bio` だけを入れ、全件の内訳を meta の `geosite_counts` に残します。
- 200 以外、転送、指定基準欄のないページがあると終了コード1で止まり、geo.db は書き換えません。

### geo.db

| table | 内容 |
| --- | --- |
| `geopark` | `slug`, `name`, `source_url`, `fetched`, `certified`（日本ジオパーク認定年月）, `unesco`, `municipalities`（JSON: prefecture, district, name, code, partial）, `geometry`（所属判定用GeoJSON）, bbox, `display_geometry`（表示用GeoJSON） |
| `geosite` | `heritage_id`（管理対象ID、ゼロ詰めのまま）, `name`, `designation`（national / special）, `designation_label`, `kind`（geo / geo+bio）, `criteria`, `prefecture`, `address`, `latitude`, `longitude`（CSV に座標がなければ null）, `source_url`, `fetched` |
| `meta` | 出典、N03 の版、簡略化の許容値、天然記念物の分類内訳、生成日（ジオパークは `built`、天然記念物は `geosite_built`） |

各スクリプトは自分のテーブルと meta のキーだけを置き換えます（`scripts/geodb.py`）。

midokoro-map は `scripts/import-data.py --kind geo --replace` で `data/geo/geo.db` に取り込みます。

## 国立公園

`uv run python scripts/nationalparks.py` で、環境省の公園一覧とEADASの「区域（国立公園）」レイヤーを取り込みます。初回は公開匿名セッションで取得し、以降は `~/cache/geo-map/nationalparks` のキャッシュから再生成します。`--refresh` は一覧・GIS設定・全区域を再取得します。一般閲覧用のセッション情報・サービス認証情報はメモリ上だけで扱い、キャッシュやDBに保存しません。追加のアカウントやランタイムの外部API呼び出しは不要です。

`nationalpark` テーブルには公園のslug・名称、公式ページ、指定、一覧掲載の面積、関係都道府県、区域サービスのURL、取得日、データ年度、原典情報、表示用geometry、修復した区域の件数を保持します。既存のgeopark/geositeテーブルは変更しません。区域データ453件を公園ごとに結合し、2026-10-12取得時点の公式35公園との全件対応を確認しました。瀬戸内海の2区域にある自己接触をShapelyで修復しました。修復で面積が1ppmまたは1e-9平方度（大きい方）を超えて変わる場合は生成を止めます。結合後は既存の表示用簡略化を適用します。輪郭が無効・空、一覧と区域の対応が欠ける、取得が途中で欠ける場合もDBを書き換えません。保存済みキャッシュも区域件数とID集合を照合し、区域の欠落や重複があれば再取得を求めて止めます。

区域は環境省公園計画書・生物多様性センターの区域データをもとにEADASが更新したデータ（メタデータは令和6年度整備）です。取得時点の公式一覧と、区域の整備時点は区別します。利用条件と選定理由は [tool-license-nationalparks.yaml](docs/tool-license-nationalparks.yaml)。背景地図、画像、ロゴ、国定・県立公園は取り込みません。
