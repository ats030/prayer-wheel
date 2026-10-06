# みどころマップ移行結果

2026年10月6日（日本時間）に初版を公開し、7日に検証と旧版停止を完了。

公開先: https://midokoro-map-736831430371.asia-northeast1.run.app/
自己ホスト: http://ubuntu-server-app:8533/
Cloud Run: ikimono-note-12205 / asia-northeast1、midokoro-map-00004-nhv、100%配信。CPU1・512Mi・最小0・最大2。

## 検証

- DB/API/ブラウザ: 祭り1428件、温泉1418件、史跡20203件、特産物1919件。4種類の検索・詳細・種類別検索条件保持・共通地図の位置/倍率保持・再訪・キーボード・連続切替を両環境で確認。
- 画面幅320/375/414/768/1440で横スクロールなし、地図領域を保持。モバイルの凡例は必要時だけ開ける。
- 初回設定を温泉に変更するブラウザ検査、設定より再訪記録を優先する検査、画面読み込み失敗時の再試行を確認。
- go test ./...、統合APIの種類別ルーティング・都道府県・登録/未登録広告URL・初回設定・保存済み要約の検査を通過。
- アプリ一覧は127 tests / 7 subtestsを通過。更新コミット6ca95f0をpushして再起動。
- mediumコードレビューの指摘を回帰テストで再現して修正。最終レビューは追加指摘なし。レビュー環境のブラウザ制限は実環境のChromium検査で補完した。
- 初回コピーのDB/要約9ファイルはmigration-manifest.jsonのSHA256と一致。要約の保存数: 祭り3101、温泉5004、史跡23305、特産物104、特産物公式1683。写真のライセンス/出典/作者情報は元のカタログを保持。

## 旧版と広告

omatsuri-map/onsen-map/shiseki-map/tokusan-mapはCloud Runサービス削除、ローカルsystemd disable --now。ソース・データ・元のデプロイスクリプトを保持する。戻し方はREADME.md参照。
残るCloud Runサービスはdekita-app/ikimono-note/midokoro-map。アプリ一覧も同じ3サービスに変更した。古いコンテナ画像・ソースアーカイブ・広告IDの既存Secretは戻す際に使用できるよう、この移行では削除していない。

新URLの広告登録が未完了のため、広告IDを新規作成せず、通常の宿泊/商品/ふるさと納税検索リンクで公開。後からURL登録と環境設定で有効にできる。旧版削除は過去の利用分や保存中のストレージ料金を取り消さない。

/healthzはGoogle Frontendの予約パスに衝突して404になったため、/healthを使う。
根拠: https://docs.cloud.google.com/run/docs/known-issues#reserved-url-paths
自己ホストはvisit-logタグと登録を確認済み。Cloud RunからLAN専用集計先へ到達できない例外はdeploy-cloudrun.shとREADME.mdに記録。
