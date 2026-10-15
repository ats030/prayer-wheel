# お経・真言の選択

## 公開する内容

| 選択肢 | 区切り | 本文と説明 |
| --- | --- | --- |
| 般若心経 | 既存29節 | 既存本文・音声・独自意訳を維持 |
| 延命十句観音経 | 10節・42字 | 十句を一節ずつ、独自意訳を付ける |
| 光明真言 | 5節・27字 | 漢字音写と日本で唱える読みの一例 |
| 仏説八大人覚経 | 45節・372字 | 古典本文全文、日本漢字音による読みと独自意訳 |
| 仏説阿弥陀経 | 112節・1,857字 | 鳩摩羅什訳の本文全文、読みの一例と独自意訳 |

一巡は一誦です。
延命十句観音経の三誦や真言の特定回数の反復を、自動では追加しません。
観音経（偈文）と六字真言は選択肢と公開パッケージから外しています。
旧`data/kannon.json`・`data/rokuji.json`とWAV・生成記録は、非公開の検証資料としてリポジトリ内に保持します。
旧公開URLにはCDNキャッシュが残ることがあるため、削除済み経文の検証はリリースを示すクエリ付きで現行配信の404を確認します。

古典の本文・伝統的な漢字音写を独自に入力し、読みを明示しています。
宗派や伝承による違いがあるため、特定宗派の公式な唱え方としては扱いません。
意訳・意味の説明は本アプリ用の独自草案で、僧侶の監修は受けていません。
真言には「意味（参考）」を表示し、確定的な逐語訳と区別します。
病気の治癒や災難を免れることを保証する記載は加えません。

## 参照と権利

- [円覚寺：延命十句観音経](https://www.engakuji.or.jp/blog/39271/) — 古典42字の本文確認。独自の意訳・和讃は使いません。
- [全生庵：お経](https://zenshoan.com/okyo_text/) — 十句の区切りと原文を照合。
- [大蔵院：延命十句観音経](https://www.daizouin.com/延命十句観音経　現代語訳｜明石の禅寺　大蔵院/) — 伝統的なカナ読みを照合。掲載訳は転載しません。
- [高野山大学：奥之院参拝次第](https://www.koyasan-u.ac.jp/cms/wp-content/uploads/2025/03/250322_R7学生生活の手引き（奥之院参拝次第）.pdf) — 光明真言のカナ読み。
- [土浦市立博物館：2019年度夏季展示室だより](https://www.city.tsuchiura.lg.jp/data/doc/1562386776_doc_44_0.pdf) — 光明真言の漢字音写・読み。
- [Wikisource：佛說八大人覺經](https://zh.wikisource.org/wiki/佛說八大人覺經) — 安世高訳と伝わる古典372字を全文照合。『正法眼蔵』の「八大人覚」とは別の経典です。
- [CiNii Books：日本校訂大蔵経](https://ci.nii.ac.jp/ncid/BA33482410) — 経名と訳者の書誌。
- [Wikisource：仏説阿弥陀経](https://ja.wikisource.org/wiki/仏説阿弥陀経) — 鳩摩羅什訳の白文1,857字を全文照合。現代語訳部分は使用しません。
- [築地本願寺：合同墓納骨者総追悼法要](https://tsukijihongwanji.jp/wtkjp/wp-content/uploads/2020/06/2020-0621-2.pdf) — 阿弥陀経の伝統的な字別の読みを参照。版面・訳文・録音は転載しません。

現代の解説・訳文・画像・録音は取り込まず、古典本文と伝統的音写を独自入力しています。
参照と採用範囲は[enmei-license.yaml](enmei-license.yaml)・[additional-sutras-license.yaml](additional-sutras-license.yaml)、既存音声の条件は[chant-license.yaml](chant-license.yaml)に記録します。

追加2経の収録範囲は、八大人覚経の「為仏弟子」から「常住快楽」、阿弥陀経の「如是我聞」から「作礼而去」までです。
標題・訳者名・巻末題は本文へ含めません。句読点と空白を除き、現行字体へ正規化した原典と全文を比較しました。
佛→仏、覺→覚、舍→舎、彌→弥、爲→為、虛→虚、增→増、佈→布、乘→乗、焰→焔などを統一し、阿㝹の字は維持しています。
阿弥陀経の「但可以無量無辺阿僧祇劫説」は、漢文と築地本願寺資料に合わせて「劫」を含めます。
六方諸仏の反復も省略しません。意訳は節ごとの独自草案であり、既存の翻訳を再利用していません。
全文照合済みの文字列ハッシュを`check-sutra-texts.py`に固定し、節の抜けや重複をビルド時に検出します。

## データと音声

`data/enmei.json`・`data/komyo.json`・`data/hachidai.json`・`data/amida.json`が原文・字別の読み・説明の原本です。
`python3 scripts/kannon-audio.py --sutra enmei --generate`で事前生成します。
`--sutra komyo`・`--sutra hachidai`・`--sutra amida`も同じ生成経路を使います。既存CLI名を互換のため維持します。
VOICEVOX 0.25.2、WhiteCULハミング3023、波音リツの歌唱クエリ6000と既存の調整を再利用します。
漢字の自動推定を使わず、字別の明示カナを解析して音素・音符へ対応させます。
`audio/<ID>-manifest.json`に本文・WAVのハッシュ、スコア、音素、長さを保持し、ビルドで照合します。
WAVは`audio/synced/<hash>/<番号>.wav`で配信し、生成メタデータは公開しません。

## 切替と失敗時

同一オリジンの固定5種類のみを読み込みます。
切替で旧音声・先読みを止め、予約・文字位置・操作数・巡数を初期化します。
速度と下部パネルの開閉状態は維持し、進行や選択は永続保存しません。
最後の選択が優先され、失敗時は選択中のお経・真言を再読み込みできます。
表示ラベルも検証完了後に切り替え、遅れた応答で別の真言のラベルへ戻らないようにします。

## 検証と復帰

- `python3 scripts/check-sutra-texts.py` — 追加2経の全文ハッシュ、全字の読み、八つの覚知・六方諸仏・終結句。
- `python3 scripts/kannon-audio.py --sutra enmei`（komyo・hachidai・amidaも同様）— 音素、原本/WAVハッシュ、文字別タイミング。
- `python3 scripts/check-sutra-switch.py --url <URL> --sutra enmei`（komyo・hachidai・amidaも同様）— 実音声、切替/競合/再試行、全節の文字・意味・巡を5幅で検証。
- `python3 scripts/check-continuous-drum.py --url <URL>` — 5種類の連続回転と停止/再開。
- `python3 scripts/check-viewport.py --sutra amida`（hachidaiも同様）— 長い全文を開いた状態で6画面サイズの操作・内部スクロール・文字拡大を検証。
- `python3 scripts/check-cloudflare.py --url <公開URL> --package dist-pages` — 全公開ファイルのハッシュ/MIMEと非公開パス。

変更コミットをrevertしてbuild・deployすれば、直前の公開内容へ戻せます。
