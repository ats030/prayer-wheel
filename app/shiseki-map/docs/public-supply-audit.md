# 公的データ供給量の実測

Issue: `ats030-sowm`。調査日: 2026-09-23。

## 結論

3万件を第1期の公開目標として確約する根拠は得られなかった。3地域の公的データを実際に取得すると、
座標と史跡分類を同時に持つレコードは東京都87件、沖縄県10件だった。北海道の埋蔵文化財包蔵地は
登録番号で12,510件あるが、訪問先かどうか、公開地点として適切かをこのデータだけでは判定できない。
3万件は長期目標として残し、初期公開の増分は出典・座標・訪問可否を確かめたものだけに限定する。

## 取得したデータと再現方法

いずれも公開データの読み取りのみ。取得物は `/tmp` に置き、リポジトリや公開データには含めない。

| 収集元 | スナップショット | 権利条件 | SHA-256 |
|---|---|---|---|
| [東京都教育庁 文化財一覧](https://catalog.data.metro.tokyo.lg.jp/dataset/t000021d0000000017) | [CSV](https://www.opendata.metro.tokyo.lg.jp/suisyoudataset/130001_cultural_property.csv)、2026-01-15更新 | CC BY 4.0。出典表示が必要 | `0ceefb11fc6a6adbf1414e7733be2754f0e6fd867bacec02db2fd1afe72a73ee` |
| [沖縄県 文化財一覧](https://data.bodik.jp/dataset/470007_bunkazai) | [2025年5月版CSV](https://data.bodik.jp/dataset/5f9f1214-be55-4af5-acc6-c6577f07d1af/resource/edcc7bd0-6c56-4dcd-81ca-cc8fcc51acdb/download/470007_cultural_property_202505.csv) | CC BY 4.0。出典表示が必要 | `25f57972a9fe70f75ed9d98d836b264edf6b1af3ac2d1cd7c3870cb7636b2460` |
| [北海道 埋蔵文化財包蔵地GIS](https://www.harp.lg.jp/opendata/dataset/1245.html) | [ZIP](https://www.harp.lg.jp/opendata/dataset/1245/resource/8680/%E5%9F%8B%E8%94%B5%E6%96%87%E5%8C%96%E8%B2%A1%E5%8C%85%E8%94%B5%E5%9C%B0.zip)、2026-03-30更新 | CC BY 4.0。出典と改変の表示が必要 | `6fcd3d140af6f66e5b944f896fc4cb6d73c7f2f07daacca0d1ac1ccc3a0873e7` |

```bash
curl -fSL 'https://www.opendata.metro.tokyo.lg.jp/suisyoudataset/130001_cultural_property.csv' -o /tmp/shiseki-tokyo-cultural.csv
curl -fSL 'https://data.bodik.jp/dataset/5f9f1214-be55-4af5-acc6-c6577f07d1af/resource/edcc7bd0-6c56-4dcd-81ca-cc8fcc51acdb/download/470007_cultural_property_202505.csv' -o /tmp/shiseki-okinawa-cultural.csv
curl -fSL 'https://www.harp.lg.jp/opendata/dataset/1245/resource/8680/%E5%9F%8B%E8%94%B5%E6%96%87%E5%8C%96%E8%B2%A1%E5%8C%85%E8%94%B5%E5%9C%B0.zip' -o /tmp/shiseki-hokkaido-sites.zip
python3 app/shiseki-map/scripts/audit_public_supply.py \
  --tokyo /tmp/shiseki-tokyo-cultural.csv \
  --okinawa /tmp/shiseki-okinawa-cultural.csv \
  --hokkaido /tmp/shiseki-hokkaido-sites.zip
```

監査スクリプトはShift_JIS系CSVとGISのGeoPackageを読み、現行 `shiseki.json` との同名候補を出す。
入力のSHA-256を出力するため、更新後の再計測と混同しない。

## 件数と品質ゲート

| 地域・データ | 原レコード | 史跡候補 | 有効座標つき候補 | 現行データとの同名候補 | 自動公開の扱い |
|---|---:|---:|---:|---:|---|
| 東京・都指定文化財 | 248 | 史跡47＋旧跡41＝88 | 87 | 3 | 文字化け3件も保留し、81件を詳細照合候補にする |
| 沖縄・国県指定史跡 | 1,474 | 99 | 10 | 3 | 89件は座標欠落。10件も訪問可否と重複を確認する |
| 北海道・埋蔵文化財包蔵地 | 12,518 GIS形状 | 登録番号12,510 | 12,518形状 | 28形状 | 立入可能性不明のため一括公開しない |

東京の1件「下宅部遺跡」は経度欄が `, 139.451301` で、機械的な数値変換に失敗した。
これは元データの表記誤りであり、座標修正の根拠を別途確認する。東京候補の構造的な抽出保留率は
1/88（1.14%）で、候補率は87/248（35.08%）。沖縄は89/99（89.90%）が座標欠落で保留し、
候補率は10/1,474（0.68%）。北海道は名称・登録番号・形状の
欠落が0件、登録番号の重なりが8形状だった。ただし、この数値は意味的な位置精度や訪問可否の
誤り率を示さない。同名候補も同一地点とは限らず、自動統合はしない。

東京の座標つき候補には `宝?山古墳`、`森?外遺跡`、`山田宗?墓` という名称の欠損も3件ある。
元資料を照合するまで保留する。残りから同名候補3件を外した81件は、利用可能曜日も記録されている。
これは詳細照合に進める件数であり、公開を承認した件数ではない。

北海道の12,518形状のうち9,334形状は「遺物包含地」、1,961形状は「集落跡」。
[提供元はポイントとポリゴンの両方の利用を求めている](https://www.harp.lg.jp/opendata/dataset/1245.html)。
中心点だけを観光スポットに変換する運用は、元データの用途と公開状態を確認するまで保留する。

## 全国規模の見込み

[文化庁の2026年5月統計](https://www.bunka.go.jp/seisaku/bunkazai/shokai/chiho_shitei/kensu.html)は、
地方指定の遺跡・史跡を都道府県3,006件、市町村13,130件、合計16,136件とする。
[国指定史跡は2026年9月時点で1,923件](https://www.bunka.go.jp/seisaku/bunkazai/shokai/shitei.html)。
単純合算は18,059件で、重複、座標欠落、訪問不可を差し引く前でも3万件に届かない。
この統計は全国の母数の目安であり、自由に再利用できる個票の供給件数を意味しない。

現行3,311件に、3地域で座標を持つ候補97件と北海道の全登録番号12,510件をすべて加えても
最大15,918件（同名候補を仮にすべて除くと15,884件）である。この計算は北海道の全遺跡を掲載できると
仮定した参考上限で、公開可能件数の推定値ではない。3地域は全国を代表する標本ではないため、
これを47都道府県へ機械的に外挿しない。

## 権利条件による除外

[ジャパンサーチ](https://jpsearch.go.jp/static/developer/webapi/ch1_intro.html)では連携DB単位でAPI提供の
承諾と権利条件が異なる。[三重県の地域文化資産DB](https://jpsearch.go.jp/api/database/search)は
5,053件あり、座標を持つレコードも確認した。しかしメタデータ権利欄が参照する
[三重県のサイトポリシー](https://www.bunka.pref.mie.lg.jp/42550034923.htm)は文書等の無断転載を禁じる。
商用サイトへの再利用許諾を確認できないため、供給量へ算入しない。

## 次の判定条件

初期増加分は東京の81件と沖縄の10件を個別照合し、出典表示、重複、位置、訪問可否を通過した件数で
決める。3万件については、他地域の自治体CSV・GISから同じ条件で再現可能な供給量が累計3万件に
達するまで公開目標に設定しない。意味的な誤り率は無作為標本の手作業照合で別途測る。
