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
