# Cloudflare公開

公開画面とAPIをWorkersへ移す。SQLiteとローカルモデルはデータ生成側に残す。
公開候補は `https://midokoro-map.ats030.workers.dev/`。
Cloud Runの停止は、このURLで一覧・詳細・外部通信・ブラウザ検証が合格した後に行う。

## 公開物と所有権

`python3 scripts/build-cloudflare.py` は4カテゴリの公開用データを一時ディレクトリへコピーし、既存Goハンドラーで一覧・都道府県別一覧・公的資料の特産物解説を書き出す。
生成途中の `data/summary-work`、SQLite、環境設定、認証情報は公開しない。
要約キャッシュはGoと同じ復旧・整形処理を通し、ハッシュの先頭2文字で分割する。
公開原本は `data/<kind>`、公開物は再生成可能な `cloudflare/assets`。
元データのSHA256を成果物のmanifestに記録する。
全件要約生成の進行中issue `ats030-yty61` はこの移行と独立し、現行公開の `summariesOnly=false` を維持する。

一覧と画像は静的ファイルで配信し、API用スナップショットはWorkerから配信する。
Wiki・Commons・Wikidataは固定の接続先へ問い合わせ、出典・ライセンス・QID照合・一時的失敗の表示を維持する。
実測でWikipedia解説の通常Worker CPUが最大24msになったため、外部API処理は無料プランで利用できるSQLite-backed Durable Objectへ移す。
URLのハッシュごとに処理を分け、記事・リクエスト・利用者情報は永続化しない。
入口のWorkerは一覧の配信とAPIの転送を行う。
住所検索は単一Durable Objectで実際の送信間隔を1.1秒以上にする。永続状態は次回送信可能時刻のみ。
住所の回答は座標をキーにエッジで1日キャッシュする。利用者の識別子を保存しない。

広告は登録済み公開オリジンとリクエストのオリジンが一致する場合だけ許可する。
初回Cloudflare公開は登録先が空なので通常検索リンク。
新URLの登録を済ませる前に広告IDを設定しない。
画像の出典・ライセンスと地図のOpenStreetMap表示は保持する。

## 更新と検証

```sh
python3 scripts/build-cloudflare.py
GOTOOLCHAIN=go1.25.0 "$HOME/go/bin/go" test ./...
"$HOME/.nvm/versions/node/v24.19.0/bin/node" --test scripts/test-cloudflare.mjs
python3 scripts/run-cloudflare.py dev --port 8797 --ip 127.0.0.1
# 別のシェルで実行
python3 scripts/browser-check.py http://127.0.0.1:8797/
python3 scripts/browser-story-check.py http://127.0.0.1:8797
```

`bash deploy-cloudflare.sh` はビルドとAPIテストの後に公開する。
`MIDOKORO_GO`、`MIDOKORO_NODE`、`MIDOKORO_WRANGLER` で既存コマンドの場所を変更できる。
OAuthは既存Wrangler設定を使い、Wrangler自身が更新する。ログ用の旧ディレクトリで設定探索がずれた場合は既存設定ディレクトリへのリンクを作る。トークンの複製・表示・リポジトリ保存はしない。

無料枠ではAPI回数・CPU・Durable Objectの制限に達するとAPIが失敗する。
静的ファイル数とサイズはビルド時に検証するが、CPUと実アクセスの適合は公開後の検証・監視が必要。
有料プランへの自動変更は行わない。条件と出典は `cloudflare-tool-license.yaml` に記録する。

## 計測と復旧

特集イベントは既存の固定イベント名を維持し、Worker標準ログへ `story_event` を出す。
Cloud Runのリクエストログとは別の保存先になるので、移行前後の集計期間を区切る。
識別子・イベント本文・参照元をアプリのログに追加しない。Cloudflareの標準ログ項目はプラットフォーム側の設定に従う。
LAN専用visit-logにはCloudflareから到達できない。自己ホスト用タグは元HTMLに残し、CSPを変更しない。
この例外は以前のCloud Run公開と同じ。

不具合が出た場合はCloudflareの以前のバージョンへ戻す。
Cloud Run停止後の復旧は `./deploy-cloudrun.sh` で既存Go版を再公開し、ポータルの公開URLを戻す。
元のソース・DB・要約、既存コンテナ画像とSecretは削除しない。
自己ホスト8533と要約生成ワーカーはこの移行で停止しない。

移行前のサービス設定はローカルの `artifacts/cloudrun-service-before.yaml` に保存する。
設定をそのまま戻す場合は、次のコマンドで再作成できる。

```sh
"$HOME/google-cloud-sdk/bin/gcloud" run services replace artifacts/cloudrun-service-before.yaml --project ikimono-note-12205 --region asia-northeast1
```

## 2026-10-10の検証記録

公開Workerバージョン: `65d54220-1664-4075-91db-02adb5cea507`。
Cloud Runとの比較で24,968件（史跡20,203、祭り1,428、温泉1,418、特産物1,919）の一覧、項目、都道府県APIが一致。
草津温泉・姫路城・川越氷川祭の概要・節・要約・出典と、特産物のWikipedia/公的資料の両経路の解説が一致。
写真の出典とライセンス、草津町の住所検索を公開URLで確認。
地図5画面幅、特集4画面幅、URL復元・共有・DNT・地図失敗時の表示が合格。
公開ログの最終API比較では通常Worker 17呼び出しのCPU最大4ms、Durable Object 5呼び出しのCPU最大28ms、いずれもoutcome=ok、例外0。
現在の料金プランの参照はOAuth権限不足（403）で未確認。プラン変更は行っていない。

最終公開バージョン: `6fe622ae-723b-41f2-9b9f-9d8117ab6a4b`。上記検証版とWorkerコードは同一で、配信ファイル数のmanifest記録を修正した。
ポータルの公開リンクをCloudflareへ変更し、稼働中APIへの反映を確認。
旧Cloud Runサービス `midokoro-map` を削除し、旧URLの404とCloudflareのhealth応答を確認。
他のCloud Runサービス、ローカルの地図サービスと要約生成ワーカーは継続稼働。

停止後のAPI比較は稼働中の自己ホスト版を参照する。データ更新後は先にスナップショットを再公開してから比較する。

```sh
python3 scripts/check-cloudflare-api.py https://midokoro-map.ats030.workers.dev --reference http://ubuntu-server-app:8533
```

## 2026-10-12のUI公開

`0c17587f`のUI/UX改善を公開した。公開バージョンは`e7bcae7a-fa84-4ed0-bd15-764f8cf9b871`。
直前の復旧先は`ae170999-a434-4e3e-82cc-817bdfd1c1e2`。
カテゴリナビ、検索欄、詳細パネル、スマートフォンの地図・検索移動に加え、未公開だった国立公園35件も反映した。

未コミットの`data/shiseki/summaries.json`は公開に含めず、コピーしたビルド用データだけをHEADの内容へ置き換えた。
そのSHA256は`0263a66863bb8b18adff347e6500b3b726658293666c949547ae73ee85590d7f`で、ビルドmanifestにも同じ値を記録した。
要約のみ表示への切替は行っていない。

公開資産1748件のビルドとWorker APIテストが成功。
公開URLで`browser-check.py`、`browser-geo-check.py`、`browser-workspace-check.py`が成功し、5カテゴリの検索・詳細・条件保持・キーボード・モバイル移動、320〜1440px、文字サイズ200%、空結果・読込失敗時の再試行を確認した。
ルートHTML、app.css、app.js、runtime.js、workspace.css、国立公園GeoJSONは検証済みビルドとバイト単位で一致した。

## 2026-10-12の地域探索公開

`07142dd2`の地域横断探索を公開した。公開バージョンは`43d18fac-3113-4fe6-8101-9632cebc997c`、直前の復旧先は`e7bcae7a-fa84-4ed0-bd15-764f8cf9b871`。
初回の入口は「地域から探す」。明示URLと最後に利用した画面の復元を維持する。
都道府県・名称・カテゴリ・地図範囲で検索し、既存カテゴリの詳細をモーダルで読む。
地域条件・確定範囲・地図位置・詳細選択をURLに保存し、閉じる/Escapeで探索位置とフォーカスへ戻る。
地図範囲は簡略化された表示形状との交差で判定し、公式境界の厳密な判定には使わない。

ジオパーク48件は既存構成自治体から都道府県を追加し、形状・集計件数が変わっていないことを確認した。
未コミット史跡要約はビルド用コピーだけをHEADへ差し替えた。要約のみ表示・料金設定は変更していない。
公開用ビルド1752資産、Worker API・探索モデル・地質生成のテストが成功し、mediumレビューの指摘を修正した。
公開URLで`browser-explore-check.py`と`browser-check.py`が成功。
熊本県271件の横断表示、5カテゴリ、名称・範囲検索、詳細・フォーカス・URL復元、部分読込失敗と再試行、320〜1440px・文字サイズ200%・スマートフォンの地域選択を確認した。
自己ホストでは既存の詳細・地形・検索フォーム回帰検証も成功した。
ルートHTML、共通UI資産、exploreの4資産、ジオパークGeoJSONが検証済みビルドと一致し、healthは正常。
