# 保留中の東京候補8件・優先照合

Issue: `ats030-jt66`。照合日: 2026-09-23。元の[候補判定表](public-candidate-review.json)で保留中の東京67件から、一般見学の可能性が高い8件を意図的に選んだ。無作為標本ではなく、[先行の12件調査](held-candidate-recheck.md)の誤り率・分母には加えない。既存地図への名称検索では8件とも同名はなかったが、同一施設・別称の重複を完全に否定するものではない。元の候補判定と公開データは変更していない。

| 元ID末尾 | 候補 | 照合できた一次情報 | 残る確認・判断 |
|---|---|---|---|
| `0118` | 徳冨蘆花旧宅 | [東京都公園協会の施設案内](https://www.tokyo-park.or.jp/park/rokakoshun-en/facility/index.html)は蘆花恒春園内の旧宅を9～16時開館と明記。[公園案内](https://www.tokyo-park.or.jp/park/rokakoshun-en/)で所在地を確認。 | 候補座標が旧宅そのものか公園の代表点か未確認。曜日だけの旧CSV案内は使わない。所在地内の訪問対象として有望、ピン位置確認まで保留。 |
| `0126` | 片倉城跡 | [八王子市の史跡案内](https://www.city.hachioji.tokyo.jp/kankobunka/003/003/001/002/p005260.html)は片倉町2475外、[城跡公園案内](https://www.city.hachioji.tokyo.jp/shisetsu/009/p011931.html)は空堀等を見られると記載。 | 元CSVの片倉町2423と市案内の2475外が一致しない。史跡範囲には複数地番の可能性があるため誤記とは断定しない。候補座標と見学地点を照合するまで保留。 |
| `0135` | 本町田遺跡 | [町田市の遺跡公園案内](https://www.city.machida.tokyo.jp/bunka/bunka_geijutsu/bunkazai/bunkazaimeguru/bunkazaimeguru/hommachida.html)は本町田3455-36他で住所が一致。復元住居内部を見学でき、9～16時30分、月曜・年末年始等休園と案内。 | 公園内の候補座標・入口位置を独立に照合する。祝日の月曜・翌日休園・整備休園があるため「火～日」だけでは不正確。追加候補として優先。 |
| `0140` | 稲荷塚古墳 | [多摩市の文化財案内](https://www.city.tama.lg.jp/kenkofukushi/1008238/1008143/1004081.html)で百草1140-1外の東京都史跡として確認。 | 一般の立入り条件と墳丘への適切な訪問点を確認できない。保留。 |
| `0144` | 戸倉城跡 | [あきる野市観光案内](https://www.city.akiruno.tokyo.jp/kanko/0000001112.html)は城山を旧戸倉城として紹介し、西戸倉・十里木からの登山経路を掲載。 | [2026年9月18日更新の通行止め一覧](https://www.city.akiruno.tokyo.jp/kanko/0000016749.html)には小和田・戸倉散策道の一部規制がある。城山への案内経路との関係、候補座標、山道の現況を確かめるまで保留。「毎日見学可」は採用しない。 |
| `0186` | 府中高札場 | [府中市の観光スポット案内](https://www.city.fuchu.tokyo.jp/kanko/kanko/spot.html)は旧甲州街道と府中街道の交差点・宮西町5-1の都旧跡として紹介。[指定一覧](https://www.city.fuchu.tokyo.jp/gyosei/fuchusinogaiyo/bunka/fuchucity_siteibunkazai.html)にも載る。 | 元CSVは宮西町5-1-1で、下記の追加照合で東京都の案内にも同じ枝番があると確認。元CSV点は公式地図点から約36m離れるため、公式地図点への補正を条件に公開候補。 |
| `0189` | 久米川古戦場 | [東村山市の指定告示](https://www1.g-reiki.net/city.higashimurayama/reiki_honbun/f200RG00000626.html)は諏訪町2丁目付近の旧跡。[市立公園案内](https://higashimurayama-parks.jp/parklist/%E8%A5%BF%E5%AE%BF%E5%85%AC%E5%9C%92/)は西宿公園を公園として案内する。 | 古戦場の指定範囲・記念碑位置と候補座標の一致を確認できない。公園への立入りと戦場全体への立入りを混同しない。保留。 |
| `0244` | 中村不折旧宅（書道博物館） | [台東区の景観重要建造物案内](https://www.city.taito.lg.jp/kenchiku/machidukuri/keikan/20100427.html)は根岸2-10-4と記載。ただし旧居宅と蔵は戦災で焼失し、現在残るのは博物館本館と書庫と明記。[区の現行企画展案内](https://www.city.taito.lg.jp/bunka_kanko/culturekankyo/shisetsubunkazai/moyoosimono/shodouhakubutsukan/90syunen.html)で博物館が開館中と確認。 | 「旧宅が現存し見学できる」と誤解させない名称・説明が必須。候補座標と現行の有料入館・休館条件を照合してから追加判断。保留。 |

今回8件は対象の存在を現行の一次情報で再確認した。府中高札場1件は下記の追加照合を経て、公式地図点への補正を条件に公開候補とした。残る7件は座標・訪問入口等の確認が残るため保留。公開データ自体は変更していない。東京の完全未照合は59件（当初67件から8件を除く）。この優先抽出結果を残る59件の品質や追加可能率へ外挿しない。

## 本町田遺跡・府中高札場の位置追加照合（同日）

- 本町田遺跡：元CSV点は `35.567928, 139.449028`。[奈良文化財研究所「文化財総覧WebGIS」掲載の町田市由来データ](https://heritagemap.nabunken.go.jp/statistic/95008081-%E6%9C%AC%E7%94%BA%E7%94%B0%E9%81%BA%E8%B7%A1.html)の世界測地系点 `35.56725, 139.4494` とは約83m離れる。両者とも史跡・公園の代表点であり得るため、片方が誤点とは断定できない。[町田市の2024年案内図](https://www.city.machida.tokyo.jp/shisei/koho/faxrelease/2024/202410.files/136.pdf)は公園への経路と所在地を示すが、座標付きの敷地境界・入口は示さない。元CSV点を訪問ピンとして採用するには、園内・入口との対応確認が残る。
- 府中高札場：元CSV点は `35.669798, 139.476383`。[東京都教育委員会の文化財公開案内](https://www.syougai.metro.tokyo.lg.jp/bunkazai/pro2018/koukaip49-58.pdf)は元CSVと同じ宮西町5-1-1、通年・終日公開と記載する。市の5-1は枝番を省いた所在地表記と両立するため、地番不一致として扱わない。[2026年更新の東京観光公式案内](https://www.gotokyo.org/jp/spot/968/index.html)も旧甲州街道と府中街道の交差点として紹介する。さらに[東京都教育委員会の現行散策案内](https://www.syougai.metro.tokyo.lg.jp/bunkazai/week/fuchu/)は通年・終日公開と記載し、サイトの[地図用データ](https://www.syougai.metro.tokyo.lg.jp/bunkazai/week/asset/js/location_fuchu.json)は「府中高札場」の点を `35.66998576441689, 139.4767130547299` とする。元CSV点とは約36m離れる。公式地図の点を訪問ピンに採用することを条件に、別途公開候補とする。元CSV点は採用しない。

距離は世界測地系の緯度経度による大円距離の概算。異なる代表点間の差を直ちに位置誤りとは見なさない。府中高札場の公開条件は現行の東京都教育委員会サイトでも確認したが、臨時の立入規制まで保証するものではない。公開データへの反映は、元の候補照合 issue とは別判断とする。
