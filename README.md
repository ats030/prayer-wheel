# 経文回向ホイール（prayer-wheel）

縦に回る1本のドラムで、心経を一句ずつ読む静的Webアプリです。
同梱の音声ファイルを再生するので、利用者側のVOICEVOXやOSの日本語音声は不要です。
スマートフォンではドラムをタップして進めます。

## 起動

```bash
cd app/prayer-wheel
VISIT_LOG_EXEMPT_REASON='公開版と同じファイルでローカル検証するため' python3 scripts/build-cloudflare.py
python3 -m http.server 8731 --bind 127.0.0.1 --directory dist
```

`http://127.0.0.1:8731` を開きます。公開する場合も、生成した`dist/`全体を同じHTTPSオリジンで配信します。
新アプリは`data/sutra-phrases.json`と`audio/phrases/*.wav`を使用し、旧データ・音声は以前のタブ用に保持します。
`file://` での直接起動は使いません。Node、Python、Nemoは利用者には不要です。
ブラウザの自動再生制限により、最初のスクロールだけで再生できない場合はドラムをタップするか
「音声を再試行」を押します。

## Cloudflareへの公開

公開URL: **https://prayer-wheel.ats030.workers.dev**

`wrangler.jsonc`は静的アセットだけを配信するWorkers設定です。
Node 22以上とWrangler 4.149.0、Cloudflareへのログインが必要です。

```bash
VISIT_LOG_EXEMPT_REASON='公開HTTPSから内部HTTPのvisit-logへ接続できないため' python3 scripts/build-cloudflare.py
npx wrangler@4.149.0 deploy --dry-run
npx wrangler@4.149.0 deploy
```

`dist/`へHTML・JS・CSS・経文・ファビコン・現行56句・旧29節・比較音声のWAVをコピーします。
内部HTTP向けvisit-logタグは公開ネットワーク例外として公開版だけ省略し、ローカル原本は保持します。
理由は課題`ats030-e5ozb`と[配信条件の記録](docs/cloudflare-license.yaml)に記録しています。
設定・テスト・生成スクリプト・音声生成メタデータは公開しません。
公開後の確認は `python3 scripts/check-browser.py --url <公開URL>` で実行できます。
`python3 scripts/check-cloudflare.py`で全公開ファイルのハッシュ・音声MIMEと非公開パスの404も確認できます。
再デプロイ時も音声検査を含むビルドを先に実行してください。

## 操作と進行

| 操作 | 動作 |
|---|---|
| 下スクロール・ドラムのクリック／タップ・↓・PageDown・Enter | 一句を予約し、中央へ一句分回って止まる |
| 逆スクロール・戻る・↑・PageUp | 末尾の未再生予約を一句取消。予約がなければ前の句を読み直す |
| 一時停止・再開・ドラムにフォーカスしてSpace | 現在位置と予約を維持して停止・再開 |
| 最初から | 音声・予約・位置・操作数・巡数をリセット |
| 速度 | 0.6–1.4倍速。再生中の音声にも適用し、ブラウザの音程維持機能を使う |
| 音声を再試行 | 失敗した句の冒頭から再生。ドラムの位置や巡数は変えない |

- 最大**5句の待ち予約＋再生中の1句**。上限で拒否された操作はドラムや位置を変えません。
- ドラム中央は最後に操作した句、上下は前後の句です。初期状態は「心経を回す」と表示します。
- ドラムは操作受付時に動き、読経欄の本文・読み仮名・進捗は実際の音声開始時に進みます。
- 連続操作は280msの短い回転で最新位置に追従し、動きを減らすOS設定ではアニメーションを省きます。
- 強調は最後に再生を開始した句の位置を示し、停止・読み込み中もその位置を保持します。
- 一時停止中の操作は予約だけを追加し、自動では再開しません。
- 先頭から前には戻りません。逆操作で完了済み巡数は減らず、末尾の再読でも重複加算しません。
- 末尾の正常な再生完了で一巡を加算します。次の操作・予約は先頭から続きます。
- ドラム下の「操作数」は受け付けた前進数から取消・後退数を引いた値です。
- 音声の読み込み・再生失敗時はその句で停止し、予約を保持します。無音で完了扱いにはしません。
- 任意テキストの読み込み、音声選択、OS音声への自動切替、進行の永続保存は初版の対象外です。

## 経文と音声

`data/sutra.json`に漢字本文と音声生成用の読み仮名を別々に記録し、元の29節を意味の区切りで56句に分けています。
古典の漢文本文を現行字体で入力し、寺院掲載本文と公開されている読みを照合しました。
現代語訳・解説・既存録音は転載していません。宗派によって字体・読み・唱え方に違いがあります。
出典と編集方針はデータ内に記録しています。

本体は試聴Dで選んだ**VOICEVOX:WhiteCUL**のノーマル・ハミングを全56句に採用しています。
エンジン0.25.2、音声ライブラリ0.16.0、歌唱クエリ生成は**VOICEVOX:波音リツ**です。
本体はMIDI50（146.8Hz）を中心に、母音を持続させて均等な拍で読みます。
母音・撥音の中央値を超えた音量だけを50%抑え、歌唱由来の膨らみを減らしています。小さい音や子音・休符の音量はそのままです。
僧侶の録音や、宗派の正式な唱法を再現した音声ではありません。

本体では一句ごとに停止・再開できるよう個別に生成し、句の終わりで音を伸ばして休符を置きます。
本体の句末は通常の拍と同じ約0.32秒、休符は約0.09秒に抑え、短句を続けて操作したときの間を短くしています。
最初のpau（無音）だけを短縮し、次の子音を切らずに句間の余分な間を抑えます。
本体は句の終端でも区切るため、5節をひと続きに生成したD試聴音声と間は完全には同じではありません。
生成query、スコア、経文・WAVのhash、長さ、読み、休符・音量調整は`audio/manifest.json`へ保存します。
読み・音素・形式・音割れは機械的に検証しますが、全編の自然さは聴感による確認が必要です。

生成時だけ、公式VOICEVOX 0.25.2（localhost:50021）と読み確認用Nemo0.24.0（localhost:50121）を起動します。
利用者に音声エンジンの導入は不要です。生成コードはPython標準ライブラリのみで動きます。

```bash
python3 scripts/generate-recitation.py
python3 scripts/check-audio.py
python3 scripts/check-recitation-browser.py  # 全56句をUI上限1.4倍で実再生
```

全56句の合成・検証に成功してから本体のWAVとmanifestを更新します。
今回の全56句採用コミットをrevertしてビルド・再公開すると、音声・生成設定・クレジットをまとめて採用前へ戻せます。
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

黒・金・生成りの経文ドラムをimagegenで生成しました。原画像は
`assets/prayer-wheel-icon-source.png`です。UIに合わせて時計回り90°に回転した編集版を
`assets/prayer-wheel-icon-horizontal.png`に保存しています。背景除去版は
`assets/prayer-wheel-icon-transparent.png`で、透過RGBAの64px `favicon.png`と32bitの32px `favicon.ico`に使用しています。
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
既存ローカルエンジン0.25.2、両ライブラリ0.16.0です。Nemoの既存A/Bを保持し、本体はD採用後、さらに56句へ細分化しています。
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

## 56句への分割

1回の操作で進む量を、元の29節から56の短い句へ変更しました。
「照見五蘊皆空／度一切苦厄」「色即是空／空即是色」など、既存の意味の区切りを使います。
漢字本文と読みをつなげた結果が分割前と同じことを検査しています。元の本文は`audition/baseline/sutra.json`で保存し、比較A〜Dも当時の本文・音声を維持します。

WhiteCULの声と通常の拍・母音の持続を維持し、音域を下げて短句の句末と休符を短縮しています。
公開する新本文は`data/sutra-phrases.json`、新音声は`audio/phrases/01.wav`〜`56.wav`です。
リポジトリでは`data/sutra.json`が現行の本文です。ビルド時にこの公開名へコピーします。
公開`data/sutra.json`と`audio/01.wav`〜`29.wav`は以前のタブ用に元のまま保持し、表示と音声がずれないようにします。
`audio/legacy-manifest.json`に旧音声hashを記録し、公開版には含めません。
合計100公開ファイル（新56＋旧29＋比較4の89 WAV）で、旧29節音声も同じWhiteCUL規約・クレジットが適用されます。
