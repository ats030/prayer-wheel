# OpenDesignによる詳細画面の比較試作

レビュー用: http://ubuntu-server-app:8533/

上部の「表示」で提案と現行を切り替える。同じ保存済みラーメン6件を使う。「100件」は表示検証用の繰り返しデータで、実際に100件の歴史を生成した結果ではない。状態・再生成操作はブラウザー内で再現し、実APIへ送信しない。ナビゲーションと「条件を変える」は本番の閲覧・入力画面へ移動する。

この試作は詳細画面の提案を確認するためのもの。ユーザー確認後に入力・一覧への展開を進める。現行の本番HTML/CSS/JS、API、保存データ、生成処理を変更していない。

## 設計の根拠

OpenDesign公式 `nexu-io/open-design` の固定commit **53231d40b778d88eba23f35547bf99485d3ae9fc**（取得2026-10-02 UTC）を使用。OpenDesignのデスクトップアプリやクラウド生成は起動していない。Codexが公式の機能スキル・設計資料を読む方式で適用した。

- `reference/minimalist-ui.md`: スキル本体。暖色系の控えめな配色、文字の強弱、平面的な構成、小さい角丸、影とグラデーションを避ける方針を適用。
- `reference/clean-design.md`: 揃ったグリッド、文字の階層、明確なフォーカスと状態表示を参照。
- 大きな余白、外部フォント・アイコン、登場アニメーション、装飾写真、青・紫の配色は採用しない。ユーザー合意の密度、紙色と緑、既存システムフォントを優先する。
- 年代を緑、出来事を太字、説明を読みやすい濃さの補助色にし、列見出しと出典の背景を薄くする。完了・生成中・失敗は文字と色で示し、操作部品を統一する。
- 原文引用は非表示。重要な進捗・失敗・時間上限・旧結果を隠さない。説明文を切り捨てず、出典操作の高さ44pxを維持。

原典: https://github.com/nexu-io/open-design/tree/53231d40b778d88eba23f35547bf99485d3ae9fc

## 再構築・検証

リポジトリrootで実行:

```sh
python3 app/timeline-generator/design-preview/build.py
.venv/bin/python app/timeline-generator/design-preview/check.py
```

`build.py`はSQLiteをread-onlyで開き、保存済みラーメンの表示項目だけを取得する。引用・照合注記を試作へコピーしない。現行detail/styles/tokens/appのソースを単一HTMLへ凍結し、そのハッシュを`baseline.json`に記録する。再構築するとその時点の現行コード・保存結果を取り込む。

`check.py`は5幅（320/375/414/768/1280）、100項目、320/1280幅の200%文字拡大、原文DOM不在、全文表示、44px操作、補足折りたたみとキーボード、完了/再生成中/時間上限/再生成失敗/0件、模擬再試行を検証する。ページエラーと実APIネットワーク送信がないことも確認。結果は`checks.json`、比較画像はPNGに保存する。

2026-10-02 UTCの最終検証はすべて成功。保存済み6件の1280×900比較は平均行高53.67px→54.5px、表示件数6件→6件。mediumの読み取り専用コードレビューでブロッカーなし。独立レビューでも凍結コード・ハッシュの一致、SQLite read-only、生成APIの隔離、保存文字列の安全な埋め込みを確認。品質評価も要求適合・範囲・検証・運用・データ保護をpassとした。これは表示の検証であり、年表内容の歴史的な正確さを再評価したものではない。

試作issue: `ats030-5a7py`。確認後の全画面展開は`ats030-hxb91`で追跡する。

## 配信・停止

レビュー用の一時サービス `timeline-generator-design-preview.service` が8533番でこのフォルダーだけを配信する。本番8532番サービスには影響しない。全HTMLにvisit-logタグを含む。サーバー再起動後は一時サービスの起動が必要。

```sh
systemd-run --user --unit=timeline-generator-design-preview --description='Timeline generator OpenDesign comparison preview' --property=WorkingDirectory=/home/ats030/app/timeline-generator/design-preview /usr/bin/python3 -m http.server 8533 --bind 0.0.0.0 --directory /home/ats030/app/timeline-generator/design-preview
systemctl --user stop timeline-generator-design-preview
```

配信停止で元の運用に戻せる。試作の採用には別途ユーザー確認が必要。

## 利用条件

ライセンス確認は`license-review.yaml`。スキルのMIT著作権表示とライセンス、OpenDesign本体のApache-2.0ライセンスを`reference/`に保存した。外部のロゴ・商標・フォント・モデル・有料プランは追加していない。
