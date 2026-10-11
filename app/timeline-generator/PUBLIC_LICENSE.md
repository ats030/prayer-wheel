# 公開生成・収益化の利用条件

確認日: 2026-10-11。追跡issue: ats030-esadh。採用記録は `tool-license.yaml` の `public_generation_review`。

## 判断

公開生成の候補はWikipedia限定とする。利用条件への対応は可能だが、現行版の品質比較が終わるまでは採用確定ではない。Cloudflareの一般公開、アフィリエイトアカウントの登録、広告の配信はこの検証に含めない。従来の静的公開は閲覧専用であり、公開生成には別途認証・個人の結果への権限検査・受付量制限が必要。

SearXNG自体のソフトウェアライセンスと、上流検索サービスへの自動アクセス条件は別である。「SearXNGだから商用不可」「Wikipediaへのリンクなら適合」という一括判断はしない。現行Google/Bing等の経路は既存審査で採用しない判定のため、公開生成に使わない。将来の公式サイト追加も、取得と再利用の条件をURL単位で確認する。

## 年表本文

Wikipediaの文章を要約・翻案した年表本文を、保守的にCC BY-SA 4.0で提供する。各項目には出典記事へのリンクを残し、著者の履歴を辿れるようにする。生成AIによる要約・改変であること、ライセンスのリンク、非公認であることを表示する。出典側に追加の帰属表示や例外がある場合は、標準フッターだけで足りると判断しない。

CC BY-SAは商用利用を許す一方、対象本文の改変・再配布時には帰属・継承条件がある。本文と分離したUI、独自ロゴ、広告枠にサイト全体のCC表示を広げない。事実そのものと創作的な表現の扱いも区別する。モデルのライセンスは、取得した文章の権利処理を代替しない。

画像・書影・ロゴは今回取り込まない。Wikipediaの記事と同じ条件で使えるとは限らず、将来追加する際は各ファイルの権利・著者・ライセンスを確認する。

生成結果に `source_mode` を保存する。静的公開の承認・書き出しは `wikipedia` の記録だけを受け付ける。SearXNG経由、または経路が不明な旧記録はURLがWikipediaでも拒否する。旧承認済み記録へのラベルの後付けは行わず、経路を確認できる限定生成と内容確認から承認し直す。既存DB・承認ファイルは自動更新しない。JSONの自己申告だけで改ざんまで証明できる仕組みではなく、管理側のアクセス制限も必要。

公開生成の画面・ダウンロード・共有にも同じ帰属表示を付ける。現在の私用詳細画面は一般公開の実装ではなく、静的テンプレートへの対応だけで公開生成が完成したとは扱わない。

## API取得

連絡先付きUser-Agent、既存の直列化・待機間隔・maxlagを維持する。APIのエラー・アクセス制限時に別検索経路へ自動で切り替えない。無料は無制限を意味しない。Wikimediaの利用指針、robots、取得制限を尊重し、制限エラーを迂回しない。

## 書籍アフィリエイト

初期案は、運用者が実在・著者・版・テーマとの関連を確認した書籍の手動リンク。広告枠の冒頭に「広告／PR：購入により運営者へ報酬が入ることがあります」と明瞭に表示する。歴史の説明と商品推薦を分離し、販売実績や読書経験を生成AIに創作させない。価格・在庫・評価・書影を無断転載せず、アフィリエイトサービスが許可する表示素材だけを使う。

楽天APIの自動書籍検索は初期採用しない。Web Service規約にはAPI収入を楽天アフィリエイト経由に限定する条件、限定利用環境、多数の人と共有できる保存への制約があり、私用画面やログイン限定画面への表示・公開キャッシュを当然に許されたものとしない。公開形態・保存方法について許可された範囲を確認してから再検討する。手動リンクにもパートナー規約、媒体登録、禁止行為、表示条件が適用される。

収入のためのクリックを依頼せず、商品広告とは別に任意支援を案内する。広告リンクは `rel="sponsored noopener"` を付ける。アフィリエイト識別子の設定・媒体条件の確認前に仮の収益リンクを配信しない。

## 根拠

- [Wikimedia利用規約・再利用と改変](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content)
- [Wikimedia API利用指針](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines)
- [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.ja)
- [楽天Web Service規約](https://webservice.rakuten.co.jp/guide/rule)
- [楽天パートナー規約](https://affiliate.rakuten.co.jp/guideline/terms/)、[ガイドライン](https://affiliate.rakuten.co.jp/guideline/rule/)
- [消費者庁・ステルスマーケティングQ&A](https://www.caa.go.jp/policies/policy/representation/fair_labeling/faq/stealth_marketing)
- [Gemma Apache-2.0](https://ai.google.dev/gemma/apache_2)、[Qwen3.8-27B LICENSE](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/LICENSE)

規約は公開直前にも確認する。モデルは既存のdigestとライセンスの記録に対応する配布物を使い、別サイズや別配布物へ条件を一般化しない。
