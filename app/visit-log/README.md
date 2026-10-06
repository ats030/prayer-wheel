# Cloud Run アクセス集計

`fetch-cloud-run-logs.py` は Cloud Logging の既存 `run.googleapis.com/requests`
を読み、日付（日本時間）・パス・種別・HTTPステータス・bot判定ごとの件数だけを
`~/data/visit-log/cloud-run-stats.json` に保存する。IP、User-Agent、クエリ、
フラグメント、個別ログやそのIDは保存しない。集計ファイルは0600。
既存のビーコンPV・訪問者数・外部公式統計とは別に表示する。

## 対象と権限

`cloud-run-config.json` の `projects` の全リージョンからサービスを自動検出する。
同名でも `project/region/service` で識別する。除外対象は同じ形式で `exclude`
に記載する。プロジェクトから消えたサービスも90日以内の件数がある間は履歴として残す。

既存gcloudログインの認証を利用する。必要な読み取り権限は Cloud Run のサービス一覧、
Cloud Logging のアクセスログ、global の `_Default` ログバケット設定。
API有効化やIAM変更は行わない。バケットやサービス一覧を読めないプロジェクトは
前回の集計を保持して失敗表示にする。

## 更新・欠測

`visit-log-cloud-logs.timer` が毎時起動する。5分の到着猶予を設け、直近2日前の
日本時間0時から再集計して日単位で置き換えるため、通常の遅延と重複を吸収する。
初回は既存の `_Default` の保存期間内を最大90日取得する。
集計の再実行は加算ではなく置き換え。取得できた範囲を区間で保存し、
長期停止による穴を含めて、未取得の日をゼロと表示しない。

過去90日（今日を含む）を保持する。既存ログ保存期間は2026-10-06の確認で30日。
最初の取得境界日・当日は「一部」、未取得日は「欠測」。Google側の保存期間は延長しない。
取得済みとは対象フィルタの検索が完了した意味で、Google側のsink除外・ログ無効化・
収集開始前の保存期間変更を証明するものではない。2日より遅れて到着したログは
通常の更新では反映できない。必要な場合は別の出力先に初回取得して確認する。

ページング中の失敗も含め、サービス単位の取得が成功した時だけその集計を更新する。
他のサービスは更新を続ける。認証全体の失敗は前回結果を保持し全体警告を表示する。
詳細なGoogle応答本文やログ本文はエラー情報として保存しない。
呼び出しを1.1秒以上空け、429/一時的5xxを再試行する。サービスごとに500ページ上限、
systemd実行は45分上限。同時実行はファイルロックで防止。

## 種別と表示

`api_prefixes` に一致するパスとGET/HEAD以外をAPI、`static_prefixes` と既知の
画像・CSS等の拡張子を静的ファイル、それ以外をページとして推定する。
アプリのルーティングによって推定が外れるため、設定でプレフィックスを調整できる。
bot/crawler/spider/headless をUser-Agentに含む場合のみbotと判定する。
それ以外は「不明」であり、人間の訪問やPVを意味しない。
パス内のメール形式・数字ID・UUID・長い英数字・認証関連ルートの直後の値は
`:id` にまとめる。任意のパス文字列の機微性を完全には判別できないため、
パス集計を扱う画面は従来どおりTailnet内に限定する。
既存の期間・bot切替を適用する。パスは最大300文字、画面は上位50パスを表示する。

## 検証・運用

```sh
.venv/bin/python app/visit-log-cloud-selftest.py -v
.venv/bin/python app/visit-log-selftest.py
.venv/bin/python app/visit-log/fetch-cloud-run-logs.py
systemctl --user status visit-log-cloud-logs.timer visit-log-cloud-logs.service
```

取り消しは `systemctl --user disable --now visit-log-cloud-logs.timer` で定期取得を止め、
この変更のコードを戻して `visit-log.service` を再起動する。既存の集計データは消さない。
画面は既存の色・書体・カード・テーブルを維持し、サービスと詳細を折りたたみ表示する。

費用・利用条件は `cloud-logging-license.yaml` に記録。
公式参照: [Logging API](https://docs.cloud.google.com/logging/docs/reference/v2/rest/v2/entries/list)、
[Cloud Run logs](https://docs.cloud.google.com/run/docs/logging)、
[費用](https://cloud.google.com/products/observability/pricing)。
