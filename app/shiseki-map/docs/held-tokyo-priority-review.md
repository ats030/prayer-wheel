# 保留中の東京候補8件・優先照合

Issue: `ats030-jt66`。照合日: 2026-09-23。元の[候補判定表](public-candidate-review.json)で保留中の東京67件から、一般見学の可能性が高い8件を意図的に選んだ。無作為標本ではなく、[先行の12件調査](held-candidate-recheck.md)の誤り率・分母には加えない。既存地図への名称検索では8件とも同名はなかったが、同一施設・別称の重複を完全に否定するものではない。元の候補判定と公開データは変更していない。

| 元ID末尾 | 候補 | 照合できた一次情報 | 残る確認・判断 |
|---|---|---|---|
| `0118` | 徳冨蘆花旧宅 | [東京都公園協会の施設案内](https://www.tokyo-park.or.jp/park/rokakoshun-en/facility/index.html)は蘆花恒春園内の旧宅を9～16時開館と明記。[公園案内](https://www.tokyo-park.or.jp/park/rokakoshun-en/)で所在地を確認。 | 候補座標が旧宅そのものか公園の代表点か未確認。曜日だけの旧CSV案内は使わない。所在地内の訪問対象として有望、ピン位置確認まで保留。 |
| `0126` | 片倉城跡 | [八王子市の史跡案内](https://www.city.hachioji.tokyo.jp/kankobunka/003/003/001/002/p005260.html)は片倉町2475外、[城跡公園案内](https://www.city.hachioji.tokyo.jp/shisetsu/009/p011931.html)は空堀等を見られると記載。 | 元CSVの片倉町2423と市案内の2475外が一致しない。史跡範囲には複数地番の可能性があるため誤記とは断定しない。候補座標と見学地点を照合するまで保留。 |
| `0135` | 本町田遺跡 | [町田市の遺跡公園案内](https://www.city.machida.tokyo.jp/bunka/bunka_geijutsu/bunkazai/bunkazaimeguru/bunkazaimeguru/hommachida.html)は本町田3455-36他で住所が一致。復元住居内部を見学でき、9～16時30分、月曜・年末年始等休園と案内。 | 公園内の候補座標・入口位置を独立に照合する。祝日の月曜・翌日休園・整備休園があるため「火～日」だけでは不正確。追加候補として優先。 |
| `0140` | 稲荷塚古墳 | [多摩市の文化財案内](https://www.city.tama.lg.jp/kenkofukushi/1008238/1008143/1004081.html)で百草1140-1外の東京都史跡として確認。 | 一般の立入り条件と墳丘への適切な訪問点を確認できない。保留。 |
| `0144` | 戸倉城跡 | [あきる野市観光案内](https://www.city.akiruno.tokyo.jp/kanko/0000001112.html)は城山を旧戸倉城として紹介し、西戸倉・十里木からの登山経路を掲載。 | [2026年9月18日更新の通行止め一覧](https://www.city.akiruno.tokyo.jp/kanko/0000016749.html)には小和田・戸倉散策道の一部規制がある。城山への案内経路との関係、候補座標、山道の現況を確かめるまで保留。「毎日見学可」は採用しない。 |
| `0186` | 府中高札場 | [府中市の観光スポット案内](https://www.city.fuchu.tokyo.jp/kanko/kanko/spot.html)は旧甲州街道と府中街道の交差点・宮西町5-1の都旧跡として紹介。[指定一覧](https://www.city.fuchu.tokyo.jp/gyosei/fuchusinogaiyo/bunka/fuchucity_siteibunkazai.html)にも載る。 | 元CSVは宮西町5-1-1で枝番が異なる。街路からの見学対象として有望だが、交差点のどちら側に候補座標があるか照合する。屋内施設のような「開館日」は付けない。 |
| `0189` | 久米川古戦場 | [東村山市の指定告示](https://www1.g-reiki.net/city.higashimurayama/reiki_honbun/f200RG00000626.html)は諏訪町2丁目付近の旧跡。[市立公園案内](https://higashimurayama-parks.jp/parklist/%E8%A5%BF%E5%AE%BF%E5%85%AC%E5%9C%92/)は西宿公園を公園として案内する。 | 古戦場の指定範囲・記念碑位置と候補座標の一致を確認できない。公園への立入りと戦場全体への立入りを混同しない。保留。 |
| `0244` | 中村不折旧宅（書道博物館） | [台東区の景観重要建造物案内](https://www.city.taito.lg.jp/kenchiku/machidukuri/keikan/20100427.html)は根岸2-10-4と記載。ただし旧居宅と蔵は戦災で焼失し、現在残るのは博物館本館と書庫と明記。[区の現行企画展案内](https://www.city.taito.lg.jp/bunka_kanko/culturekankyo/shisetsubunkazai/moyoosimono/shodouhakubutsukan/90syunen.html)で博物館が開館中と確認。 | 「旧宅が現存し見学できる」と誤解させない名称・説明が必須。候補座標と現行の有料入館・休館条件を照合してから追加判断。保留。 |

今回8件は対象の存在を現行の一次情報で再確認したが、座標と訪問入口の照合が完了していないため、公開可能件数には数えない。特に本町田遺跡と府中高札場を次の位置照合対象とする。東京の完全未照合は59件（当初67件から8件を除く）。この優先抽出結果を残る59件の品質や追加可能率へ外挿しない。
