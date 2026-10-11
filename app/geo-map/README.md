# geo-map

midokoro-map が使う地形・地質データの正本です。サービスは持たず、`data/geo.db` を生成して git で管理します。

## ジオパーク

```bash
uv run python scripts/geoparks.py            # キャッシュから再生成
uv run python scripts/geoparks.py --refresh  # geopark.jp を再取得してから再生成
uv run pytest
```

- 地域一覧と構成自治体: [日本ジオパークネットワーク](https://geopark.jp/geopark/) の一覧ページと各地域ページ。HTML コメントで外された地域は撤退済みとして除きます。
- 範囲: [国土数値情報 行政区域データ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html) N03-20260101 の市区町村ポリゴンを結合し、約50m (0.0005度) で簡略化します。
- 「山口市（阿東地域）」のように一部だけが含まれる自治体は `partial` として記録し、範囲には含めません。
- 一覧ページの自治体数と地域ページの構成自治体数を照合します。食い違いは地域ページを正とし、既知のものは `KNOWN_COUNT_GAPS` に理由を書きます。
- 取得は1秒間隔です。ページは `~/cache/geo-map/pages`（取得日は `meta.json`）、N03 は `~/cache/geo-map/n03` に置きます。
- 構成自治体を読めない地域、未解決の自治体、範囲なしの地域、自治体数の食い違いがあると終了コード1で止まります。

### geo.db

| table | 内容 |
| --- | --- |
| `geopark` | `slug`, `name`, `source_url`, `fetched`, `certified`（日本ジオパーク認定年月）, `unesco`, `municipalities`（JSON: prefecture, district, name, code, partial）, `geometry`（GeoJSON）, bbox |
| `meta` | 出典、N03 の版、簡略化の許容値、生成日 |

midokoro-map は `scripts/import-data.py` で `data/geo/geo.db` に取り込みます。
