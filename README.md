# 経文回向ホイール（prayer-wheel）

縦に回る1本のマニ車で、心経を意味のまとまりごとに読む静的Webアプリです。
同梱の音声ファイルを再生するので、利用者側のVOICEVOXやOSの日本語音声は不要です。
スマートフォンではマニ車をタップして進めます。

## AdSenseのサイト所有確認

公開HTMLに`google-adsense-account`メタタグを設定しています。
パブリッシャーIDはユーザー指定の`pub-8787627445197940`です。
現在は所有確認の準備段階で、広告スクリプト・広告枠は追加していません。
AdSenseの「サイト」へ公開URLを登録し、「メタタグ」の方法で所有確認を行って審査をリクエストしてください。
登録可能なドメインと審査結果はAdSense画面で確認します。サイト承認を保証するものではありません。
メタタグで所有確認に失敗する場合は、確認方法を「ads.txt」に切り替えられます。
`https://prayer-wheel.ats030.workers.dev/ads.txt`にも同じIDの確認行を公開しています。
AdSenseに登録したドメインが公開先と一致するかも確認してください。
現在AdSenseに表示されている登録先は`ats030.workers.dev`ですが、このホストは名前解決できず、
確認タグやads.txtを取得できません。実配信は`prayer-wheel.ats030.workers.dev`です。
Public Suffix Listには`workers.dev`が登録されており、現配信URLはその直下の`ats030.workers.dev`のさらに下です。
AdSenseが上位ドメインにまとめる場合は、到達可能な独自ドメインなどに公開先を変更して申請する必要があります。
根拠: [AdSenseのサイト管理](https://support.google.com/adsense/answer/12170421?hl=ja)、[Public Suffix List](https://publicsuffix.org/list/public_suffix_list.dat)。
手順は[AdSense公式のサイト追加案内](https://support.google.com/adsense/answer/12169212?hl=ja)を参照してください。
承認後の広告は読経操作から離れたページ下部1枠を予定し、マニ車操作による更新は行いません。

## 任意の開発支援

読経欄の「浄財」ボタンから、Buy Me a Coffeeで開発者へ任意のチップを送れます。
支援先は https://buymeacoffee.com/ats030 です。支援の有無によって利用できる機能は変わりません。
公開ビルドで`support-config.json`から外部リンクを設定します。
支援ページの説明文、用途の確認事項、公開手順は[開発支援](docs/support.md)を参照してください。

## 起動

```bash
cd app/prayer-wheel
VISIT_LOG_EXEMPT_REASON='公開版と同じファイルでローカル検証するため' python3 scripts/build-cloudflare.py
python3 -m http.server 8731 --bind 127.0.0.1 --directory dist
```

`http://127.0.0.1:8731` を開きます。公開する場合も、生成した`dist/`全体を同じHTTPSオリジンで配信します。
新アプリは`data/sutra-sections.json`と`audio/sections/*.wav`を使用し、旧データ・音声は以前のタブ用に保持します。
`file://` での直接起動は使いません。Node、Python、Nemoは利用者には不要です。
ブラウザの自動再生制限により、最初のスクロールだけで再生できない場合はマニ車をタップするか
「音声を再試行」を押します。

## Cloudflareへの公開

### Pagesへの追加公開

AdSenseの登録ドメイン問題を避けるため、Pagesの`<プロジェクト名>.pages.dev`へ追加配信する方針です。
公開URL: **https://prayer-wheel-ats030.pages.dev/**
プロジェクト名は`prayer-wheel-ats030`、本番ブランチは`master`です。
AdSenseへは`prayer-wheel-ats030.pages.dev`を新しいサイトとして登録します。
既存Workersは維持しています。AdSense側での所有確認と審査は未完了です。

```bash
VISIT_LOG_EXEMPT_REASON='公開HTTPSから内部HTTPのvisit-logへ接続できないため' python3 scripts/build-pages.py
npx wrangler@4.149.0 pages project create prayer-wheel-ats030 --production-branch master --force
npx wrangler@4.149.0 pages deploy ../dist-pages --cwd pages --project-name prayer-wheel-ats030 --branch master
python3 scripts/check-cloudflare.py --url <実際のPages公開URL> --package dist-pages
python3 scripts/check-browser.py --url <実際のPages公開URL>
```

プロジェクト作成は初回だけです。既存プロジェクトの更新はbuildとdeployだけを実行します。

Pagesは`dist-pages/`だけをアップロードします。トップレベルの`404.html`を追加し、
非公開ファイルや存在しないパスがSPAのトップ画面で200を返すことを防ぎます。
確認タグ・ads.txt・音声はWorkers版と同じです。Pages Freeの静的配信だけを使い、Functionsは使いません。
Direct Uploadを選ぶため、同じプロジェクトを後からGit連携方式へ切り替えることはできません。
条件は[Pages利用条件の記録](docs/cloudflare-pages-license.yaml)です。
停止する場合はWorkersのURLへ戻します。AdSenseの所有確認・審査は別途必要です。

### 既存Workers

公開URL: **https://prayer-wheel.ats030.workers.dev**

`wrangler.jsonc`は静的アセットだけを配信するWorkers設定です。
Node 22以上とWrangler 4.149.0、Cloudflareへのログインが必要です。

```bash
VISIT_LOG_EXEMPT_REASON='公開HTTPSから内部HTTPのvisit-logへ接続できないため' python3 scripts/build-cloudflare.py
npx wrangler@4.149.0 deploy --dry-run
npx wrangler@4.149.0 deploy
```

`dist/`へHTML・JS・CSS・経文・ファビコン・現行29区切り・互換用56句・旧29節・比較音声のWAVをコピーします。
内部HTTP向けvisit-logタグは公開ネットワーク例外として公開版だけ省略し、ローカル原本は保持します。
理由は課題`ats030-e5ozb`と[配信条件の記録](docs/cloudflare-license.yaml)に記録しています。
設定・テスト・生成スクリプト・音声生成メタデータは公開しません。
公開後の確認は `python3 scripts/check-browser.py --url <公開URL>` で実行できます。
`python3 scripts/check-cloudflare.py`で全公開ファイルのハッシュ・音声MIMEと非公開パスの404も確認できます。
再デプロイ時も音声検査を含むビルドを先に実行してください。

## 操作と進行

スマホでもマニ車と現在の一節を左右に並べ、読経欄の進捗の下に「浄財」を表示します。
現在の一節の読み仮名の下に、対応する現代語訳（意訳）を表示します。
訳文と編集方針は[現代語訳](docs/modern-translations.md)に記録しています。
「経文をひらく」で全文を表示し、「読み方を整える」で速度・最初から・詳しい操作を開けます。
戻る・一時停止／再開の専用ボタンは設けず、マニ車上の逆スクロール・↑キー・Spaceで操作します。全文を開くと読み上げ中の一節に位置を合わせます。

| 操作 | 動作 |
|---|---|
| 下スクロール・マニ車のクリック／タップ・↓・PageDown・Enter | 一節を予約し、その節の読み上げ開始と同時にマニ車が回る |
| 逆スクロール・↑・PageUp | 末尾の未再生予約を一節取消。予約がなければ前の節を読み直す |
| マニ車にフォーカスしてSpace | 現在位置と予約を維持して停止・再開 |
| 最初から | 音声・予約・位置・操作数・巡数をリセット |
| 速度 | 0.6–1.4倍速。再生中の音声にも適用し、ブラウザの音程維持機能を使う |
| 音声を再試行 | 失敗した節の冒頭から再生。マニ車の位置や巡数は変えない |

- 最大**5節の待ち予約＋再生中の1節**。上限で拒否された操作はマニ車や位置を変えません。
- マニ車は読み上げの文字を1字ずつ表示し、上下4字ずつ、約9字が見える密度で並べます。字間の横線はなく、太字と左右の印で現在字を示します。初期状態の中央は空白です。
- マニ車は音声の再生時刻に追従し、本文・読み仮名・節の進捗は読み上げ開始に合わせて進みます。節間の待ち時間は増やしません。予約の追加・取消で表示を先へ飛ばしません。
- 文字の間隔は一定で、各文字を読む時間に合わせて速度を変えます。一時停止・読み込み待ち・エラーでは表示も止まり、再生速度の変更にも追従します。OSの動作低減設定では文字単位で切り替え、補間スクロールを省きます。
- 強調は最後に再生を開始した節の位置を示し、停止・読み込み中もその位置を保持します。
- 一時停止中の操作は予約だけを追加し、自動では再開しません。
- 先頭から前には戻りません。逆操作で完了済み巡数は減らず、末尾の再読でも重複加算しません。
- 末尾の正常な再生完了で一巡を加算します。次の操作・予約は先頭から続きます。
- マニ車下の「操作数」は受け付けた前進数から取消・後退数を引いた値です。
- 音声の読み込み・再生失敗時はその節で停止し、予約を保持します。無音で完了扱いにはしません。
- 任意テキストの読み込み、音声選択、OS音声への自動切替、進行の永続保存は初版の対象外です。

## 経文と音声

`data/sutra.json`に漢字本文と音声生成用の読み仮名を別々に記録し、以前の29節と同じ意味の区切りを使います。
古典の漢文本文を現行字体で入力し、寺院掲載本文と公開されている読みを照合しました。
現代語訳・解説・既存録音は転載していません。宗派によって字体・読み・唱え方に違いがあります。
出典と編集方針はデータ内に記録しています。

本体は試聴Dで選んだ**VOICEVOX:WhiteCUL**のノーマル・ハミングを全29区切りに採用しています。
エンジン0.25.2、音声ライブラリ0.16.0、歌唱クエリ生成は**VOICEVOX:波音リツ**です。
本体はMIDI50（146.8Hz）を中心に、母音を持続させて均等な拍で読みます。
母音・撥音の中央値を超えた音量だけを50%抑え、歌唱由来の膨らみを減らしています。小さい音や子音・休符の音量はそのままです。
僧侶の録音や、宗派の正式な唱法を再現した音声ではありません。

本体では意味のまとまりごとに停止・再開できるよう個別に生成し、句の終わりで音を伸ばして休符を置きます。
本体の句末は通常の拍と同じ約0.32秒、休符は約0.09秒に抑え、各節を続けて操作したときの間を短くしています。
最初のpau（無音）だけを短縮し、次の子音を切らずに句間の余分な間を抑えます。
本体は句の終端でも区切るため、5節をひと続きに生成したD試聴音声と間は完全には同じではありません。
生成query、スコア、経文・WAVのhash、長さ、読み、休符・音量調整は`audio/manifest.json`へ保存します。
読み・音素・形式・音割れは機械的に検証しますが、全編の自然さは聴感による確認が必要です。

生成時だけ、公式VOICEVOX 0.25.2（localhost:50021）と読み確認用Nemo0.24.0（localhost:50121）を起動します。
利用者に音声エンジンの導入は不要です。生成コードはPython標準ライブラリのみで動きます。

```bash
python3 scripts/generate-recitation.py
python3 scripts/check-audio.py
python3 scripts/check-recitation-browser.py  # 全29区切りをUI上限1.4倍で実再生
```

全29区切りの合成・検証に成功してから本体のWAVとmanifestを更新します。
今回の29区切り復元コミットをrevertしてビルド・再公開すると、音声・生成設定・クレジットをまとめて採用前へ戻せます。
採用音源と規約の記録は[音声利用条件](docs/audio-license.yaml)、詳細は[音源選定記録](docs/chant-license.yaml)を参照してください。
再利用・再配信時は **VOICEVOX:WhiteCUL / VOICEVOX:波音リツ（歌唱クエリ生成）** を表記し、
[VOICEVOX規約](https://voicevox.hiroshiba.jp/term/)、[WhiteCUL規約](https://www.whitecul.com/guideline)、
[波音リツ規約](https://www.canon-voice.com/terms/)を守ってください。

## 検証

```bash
npm test
python3 scripts/check-audio.py
python3 scripts/check-browser.py
```

Nodeのテストは予約・逆操作・周回・失敗復旧・古い再生通知の無効化を確認します。
音声検査は経文と全音声のハッシュ・形式・音割れを確認します。
ブラウザ検査は配信中の`http://127.0.0.1:8731`を使用し、既存のPython Playwright/Chromium環境で
実WAVの再生、PCとタッチ画面、エラー復旧を確認します。実機iOSでの検証とは区別します。

`DESIGN.md`の既存デザインを維持し、HTMLのvisit-logタグも保持しています。

## ファビコン

黒・金・生成りの経文マニ車をimagegenでフラット化しました。
現在の透過マスターは`assets/prayer-wheel-icon-flat.png`です。陰影と装飾を抑え、
マニ車をほぼ正方形に広げて外周の余白を詰めています。
64pxのRGBA `favicon.png`と、16/32/48/64pxを含む`favicon.ico`に使用します。
既存環境のPillow 12.2.0でマスターをLANCZOS縮小し、ICOの複数サイズも同じマスターから生成します。
本体と試聴ページの参照URLには`?v=flat-20261015`を付け、旧画像のキャッシュと区別します。
旧画像は`assets/prayer-wheel-icon-source.png`、`assets/prayer-wheel-icon-horizontal.png`、
`assets/prayer-wheel-icon-transparent.png`として保持しています。
app-portalも公開アプリから同じファビコンを取得します。原画像は公開パッケージに含めません。

## 読経調の試聴版

[比較ページ](https://prayer-wheel.ats030.workers.dev/audition/)で「観自在菩薩」から5節を聴き比べられます。
Aは本体変更前のNemo WAVのPCMをそのまま連結、BはNemo男声1で同じ読みと語の区切りを保ち、母音長と音高のばらつき・抑揚・節間を抑えた調整案です。
現在の本体はDと同じWhiteCULの声を低音・均等拍へ調整しています。比較A〜Dは当時の音声を保持し、1.0倍で再生します。
Dを選択したため本体の全節へ適用しました。自然さや読みの聞き取りやすさは試聴で確認します。
Bは節を個別生成して連結するため、節境界のピッチや息継ぎの連続性までは保証しません。

```bash
python3 scripts/generate-audition.py --engine http://127.0.0.1:50121
python3 scripts/check-audition.py
```

`audition/manifest.json`に5節の読み・生成query・設定・hashを保存します。比較用WAVとHTML/CSS/JSだけを公開し、manifestと生成スクリプトは配信しません。
旧Nemoの比較元は`audition/baseline/`へ保存しました。`scripts/generate-audio.py`はこの保存先だけを更新し、本体の`audio/`は変更しません。

## 母音持続・低音のC試聴版

同じ[比較ページ](https://prayer-wheel.ats030.workers.dev/audition/)にCを追加しました。
Cは**VOICEVOX:麒ヶ島宗麟**のハミングで、歌唱クエリは**VOICEVOX:波音リツ**を使用します。
既存ローカルエンジン0.25.2、両ライブラリ0.16.0です。Nemoの既存A/Bを保持し、本体はDの低音調整を保ち、意味ごとの29区切りへ戻しています。
Cでは声と生成方式が変わるため、A/Bとの違いはテンポだけではありません。

低音の設計値はMIDI46（116.54Hz）、1モーラ約0.32秒、まとまりの最後は約0.48秒、
息継ぎ相当の休符は約0.30秒です。促音「ッ」の音符は約0.19秒に短縮し、余りを直前の母音へ回します。
休符は「行深般若波羅蜜多時」「照見五蘊皆空」「度一切苦厄」「空不異色」「空即是色」の後です。
「観自在菩薩」や対になる短い句の間には休符を入れず、句点ごとに息継ぎする設計ではありません。
69モーラを歌唱スコアで指定し、木魚・鐘・追加残響・声の重ね合わせは使いません。
全体のRMSをAと揃えて大きさによる比較の偏りを抑えますが、知覚される音量が完全に同じとは限りません。
読みのモーラ列を保持し、長母音、促音や撥音の聞き取りやすさはユーザー試聴で確認します。
Cの自然さ・読経らしさ・宗派の唱法への一致は自動検査では保証しません。

参考は[全国曹洞宗青年会の練習動画](https://sousei.gr.jp/2907/)です。
補助資料として[曹洞宗東海管区教化センターの公開音声](https://soto-tokai.net/ok_han.html)を数値分析しました。
80ms窓の自己相関で最初の120秒の音高を推定し、中央値は117.6Hzでした。
鐘や複数声・オクターブ誤りが混ざり得る概算で、単独の発声や息継ぎの位置を聴いて確認したものではありません。
数値記録は`docs/chant-reference-analysis.json`。Cの休符位置は経文のまとまりから独自に設計し、
参考録音の切り出し・同梱・転載・声の複製はしていません。曹洞宗の公式音源・監修音声とは表示しません。

```bash
python3 scripts/generate-chant.py --engine http://127.0.0.1:50021
python3 scripts/check-chant.py
python3 scripts/check-audition-browser.py
```

`audition/chant-manifest.json`にスコア・生成query・音源ID/バージョン・生成物hash・音量調整を記録します。
公開対象へ追加するのは`audition/chant.wav`と`audition/chant-female.wav`です。manifest・生成コード・参考分析は配信しません。
C/D追加のコミットをrevertしてビルド・再公開すれば、パネル・許可リスト・検証件数をまとめて元のA/B版へ戻せます。

費用・採否・条件は[音源選定記録](docs/chant-license.yaml)にまとめています。
C音声を再利用・再配布する場合は **VOICEVOX:麒ヶ島宗麟 / VOICEVOX:波音リツ（歌唱クエリ生成）** と表記し、
[VOICEVOX利用規約](https://voicevox.hiroshiba.jp/term/)、
[VirVox利用規約](https://www.virvoxproject.com/voicevoxの利用規約)、
[波音リツ利用規約](https://www.canon-voice.com/terms/)を守ってください。

### 女性版Dとの比較

Dは**VOICEVOX:WhiteCUL**のノーマル・ハミングです。男性Cは維持しています。
本文・69モーラ・拍・促音の長さ・休符位置をCと揃え、音域はMIDI55（196.0Hz）へ変えています。
音源と音域の両方が違うため、声質だけを同じ音高で比較する実験ではありません。
Dも声のみで、AにRMSを合わせています。生成記録は`audition/chant-female-manifest.json`、公開音声は`audition/chant-female.wav`です。

```bash
python3 scripts/generate-chant.py --voice whitecul  # Dだけを再生成
python3 scripts/generate-chant.py --voice sorin     # Cだけを再生成
```

`--voice`を省略すると両方生成します。D音声を再利用・再配布する場合は
**VOICEVOX:WhiteCUL / VOICEVOX:波音リツ（歌唱クエリ生成）**と表記し、
[VOICEVOX利用規約](https://voicevox.hiroshiba.jp/term/)、
[WhiteCUL利用規約](https://www.whitecul.com/guideline)、
[波音リツ利用規約](https://www.canon-voice.com/terms/)を守ってください。

## 意味ごとの29区切り

短句への56分割をやめ、元の29節と同じ本文・読み・区切りに戻しました。
「色即是空／空即是色」などを含むまとまりを1回の操作で進めます。
WhiteCULの低音・均等拍・母音の膨らみを抑える調整と短い休符は維持しています。
公開本文は`data/sutra-sections.json`、音声は`audio/sections/01.wav`〜`29.wav`です。
現行の本文はリポジトリの`data/sutra.json`です。
以前から開いているタブ用に、56句の`data/sutra-phrases.json`と`audio/phrases/`、
初期29節の`data/sutra.json`と`audio/01.wav`〜`29.wav`もそのまま公開します。
旧音声のhashは非公開の`audio/phrases-manifest.json`と`audio/legacy-manifest.json`で検証します。
公開163ファイル・147WAVです。

## 一文字ずつの音声同期

操作と音声は29節のまま、マニ車上の276文字を等間隔で縦に流します。
`data/character-readings.json`が文字ごとの字音の正本です。
字音の連結は現行の読みと一致させ、促音・撥音・拗音を含むモーラごとに照合します。
`scripts/character-timing.py`が音声のphoneme/note_idと先頭のトリムから各字のstart/endを導出します。
ビルド時に`data/character-timing.json`として公開し、元の字音表・合成manifestは非公開です。
各区間はWAVのhashに結び付け、音声は`audio/synced/<hash>/<節番号>.wav`で配信します。
同じ音声を既存パスにも残して旧タブを維持します。本文のhashと音声パスのhashを読み込み時にも照合し、再生成時は対応表を再検証します。

表示位置は`audio.currentTime`から求め、各字の発音区間の中ほどで中心線を通過させます。
節間には1字分の空白を置き、既存の節末休符中に通過させます。音声の間は延ばしません。
48面・7.5度刻みで配置し、節の内部の休符では中間位置を保持します。
停止・再試行・戻るは音声時刻が基準です。読み込みでcurrentTimeがリセットされても、
新しい節の再生開始までは直前の表示を保ちます。
合成時の音素境界を使うため、実際の発声を人が聞いて付けたアノテーションとは異なります。

`python3 scripts/character-timing.py`で全字を検証し、
`python3 scripts/check-recitation-browser.py --url http://127.0.0.1:8743`で実音声一巡・全字表示を確認できます。
旧節マニ車への復帰は文字スクロール導入コミットをrevertしてビルド・再公開します。
旧タブ用に`drum-motion.js`も保持しています。
