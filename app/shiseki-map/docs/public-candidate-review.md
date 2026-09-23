# 公的候補91件のレコード別判定

Issue: `ats030-0blv`。判定日: 2026-09-23。

全91件の名称、座標、指定分類、住所、現行地図との同名・近接関係、訪問情報、出典、
`publish`/`hold` と理由は [判定表](public-candidate-review.json) に記録した。
`publish` は判定時点では取り込み候補を意味した。2026-09-23にこの3件を
[確認済み追加データ](../data/verified_public_sites.json)として地図へ反映した。
当初の保留88件は、この判定時点では地図へ反映していなかった。
この段落と下表は当初判定の記録である。後続の追加判断は末尾を参照。

## 判定結果

| 項目 | 件数 |
|---|---:|
| レコード別判定 | 91 |
| 公開候補 | 3 |
| 保留 | 88 |
| 現行の自治体公開情報で訪問を再確認 | 4 |
| その4件で旧CSVの訪問情報と明確な相違 | 2 |
| 現行地図との同名候補 | 3 |
| 現行地図との名称違い候補 | 5 |
| 別レコードと座標を共有 | 17 |

沖縄の10件はすべて那覇市の地点で、元CSVの訪問可能曜日が空欄だった。
うち3件は現行地図と同名、5件は名称違いで同一地点の可能性がある。
名称違い候補を含む8/10件（80%）は統合・重複審査が必要であり、重複確定率ではない。
[弁之御嶽と弁ヶ嶽](https://www.library.pref.okinawa.jp/archive/contents/cat39/cat/cat1/view8-02.html)も
名称違い候補に含めたが、地図上の座標は約619m離れており同一地点とは確定していない。
後続の[無作為標本再照合](held-candidate-recheck.md)では、文化庁の指定文化財DBにより
両名称が同一対象と確定した。上記は当初判定時点の記録であり、既存点と候補点の
どちらが適切な訪問地点かは引き続き未確認である。
沖縄CSVの `NO` は全件空欄のため、判定表のIDは2025年5月版内だけの仮IDとする。
別版への継続IDは個別照合するまで確定しない。
同一座標は東京13件、沖縄4件。墓地や史跡群の代表点である可能性があり、
座標が同じという理由だけでは統合しない。

東京の元CSVは史跡・旧跡88件すべての「最終確認日」が2019-03-29だった。
現在の公開情報を確認した4件のうち、[多摩川台古墳群](https://www.city.ota.tokyo.jp/shisetsu/park/tamagawadai.html)は
CSVの時間が公園ではなく展示室のものに近く、[子規庵](https://t-navi.city.taito.lg.jp/spot/1062)は
公開曜日が現行案内と異なる。訪問情報の相違は確認した4件中2件（50%）だが、
意図して選んだ4件なので91件全体の誤り率へ外挿できない。
名称・指定分類・座標の重大誤り率も、独立した現地資料の照合が4件に限られるため未推定。

公開候補3件は多摩川台古墳群、[野毛大塚古墳](https://www.setagayadigitalmuseum.jp/information/842/detail/)、
子規庵。公開時に2019年CSVの営業時間・公開曜日を転載しない。
[世田谷代官屋敷](https://www.setagayadigitalmuseum.jp/information/other/131495380/)は
座敷公開が季節運用で、現時点の案内が次回秋開催となっているため保留した。
残る東京77件は現在の訪問情報を個別確認できていないため保留した。

## 再実行

[前段の監査](public-supply-audit.md)で記録したSHA-256に一致するCSVを使う。
入力が更新されていたらこのスクリプトは停止し、新しいスナップショットとして監査し直す。

```bash
python3 app/shiseki-map/scripts/review_public_candidates.py \
  --tokyo /tmp/shiseki-tokyo-cultural.csv \
  --okinawa /tmp/shiseki-okinawa-cultural.csv \
  --output /tmp/shiseki-public-candidate-review.json
```

元データの商用再利用・出典条件は [tool-license.yaml](tool-license.yaml) に記録済み。
出典はレコードごとに判定表へ格納した。公開を実施するならそのリンクをUIにも表示する。

## 後続の追加判断

Issue `ats030-tjrm` で府中高札場を個別照合し、[府中市のCC BY公開データ](https://www.city.fuchu.tokyo.jp/gyosei/opendata/index.html)の座標と[市の現行観光案内](https://www.city.fuchu.tokyo.jp/kanko/kanko/spot.html)を用いて4件目として追加した。[当初の判定表](public-candidate-review.json)は無作為標本の再現性のため変更していない。位置と利用条件の判断は[東京候補の後続照合](held-tokyo-priority-review.md)に記録した。
