# 経文回向ホイール（prayer-wheel）

縦に回る1本のドラムで、心経を一節ずつ読む静的Webアプリです。
同梱の音声ファイルを再生するので、利用者側のVOICEVOXやOSの日本語音声は不要です。
スマートフォンではドラムをタップして進めます。

## 起動

```bash
cd app/prayer-wheel
python3 -m http.server 8731 --bind 127.0.0.1
```

`http://127.0.0.1:8731` を開きます。公開する場合は、このディレクトリのHTML、JS、CSS、
`data/sutra.json`、`audio/*.wav`、`favicon.png`、`favicon.ico`を同じHTTPSオリジンで静的配信してください。
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

`dist/`へHTML・JS・CSS・経文・ファビコン・全29節のWAVだけをコピーします。
内部HTTP向けvisit-logタグは公開ネットワーク例外として公開版だけ省略し、ローカル原本は保持します。
理由は課題`ats030-e5ozb`と[配信条件の記録](docs/cloudflare-license.yaml)に記録しています。
設定・テスト・生成スクリプト・音声生成メタデータは公開しません。
公開後の確認は `python3 scripts/check-browser.py --url <公開URL>` で実行できます。
`python3 scripts/check-cloudflare.py`で全公開ファイルのハッシュ・音声MIMEと非公開パスの404も確認できます。
再デプロイ時も音声検査を含むビルドを先に実行してください。

## 操作と進行

| 操作 | 動作 |
|---|---|
| 下スクロール・ドラムのクリック／タップ・↓・PageDown・Enter | 一節を予約し、中央へ一節分回って止まる |
| 逆スクロール・戻る・↑・PageUp | 末尾の未再生予約を一節取消。予約がなければ前の節を読み直す |
| 一時停止・再開・ドラムにフォーカスしてSpace | 現在位置と予約を維持して停止・再開 |
| 最初から | 音声・予約・位置・操作数・巡数をリセット |
| 速度 | 0.6–1.4倍速。再生中の音声にも適用し、ブラウザの音程維持機能を使う |
| 音声を再試行 | 失敗した節の冒頭から再生。ドラムの位置や巡数は変えない |

- 最大**5節の待ち予約＋再生中の1節**。上限で拒否された操作はドラムや位置を変えません。
- ドラム中央は最後に操作した節、上下は前後の節です。初期状態は「心経を回す」と表示します。
- ドラムは操作受付時に動き、読経欄の本文・読み仮名・進捗は実際の音声開始時に進みます。
- 連続操作は280msの短い回転で最新位置に追従し、動きを減らすOS設定ではアニメーションを省きます。
- 強調は最後に再生を開始した節の位置を示し、停止・読み込み中もその位置を保持します。
- 一時停止中の操作は予約だけを追加し、自動では再開しません。
- 先頭から前には戻りません。逆操作で完了済み巡数は減らず、末尾の再読でも重複加算しません。
- 末尾の正常な再生完了で一巡を加算します。次の操作・予約は先頭から続きます。
- ドラム下の「操作数」は受け付けた前進数から取消・後退数を引いた値です。
- 音声の読み込み・再生失敗時はその節で停止し、予約を保持します。無音で完了扱いにはしません。
- 任意テキストの読み込み、音声選択、OS音声への自動切替、進行の永続保存は初版の対象外です。

## 経文と音声

`data/sutra.json`に漢字本文と音声生成用の読み仮名を別々に記録し、29節に分けています。
古典の漢文本文を現行字体で入力し、寺院掲載本文と公開されている読みを照合しました。
現代語訳・解説・既存録音は転載していません。宗派によって字体・読み・唱え方に違いがあります。
出典と編集方針はデータ内に記録しています。

音声は**VOICEVOX Nemo 男声1**、エンジン0.24.0、音声ライブラリ0.15.0を使用。
話速0.85、抑揚0.65で事前生成した読み上げです。僧侶の読経録音ではありません。
生成設定、経文ハッシュ、各音声のハッシュ・長さ・生成された読みは`audio/manifest.json`に記録します。
生成された読みとWAVの形式・音割れは機械的に検証できますが、聴感による最終確認とは区別します。

生成する場合だけ、公式のNemoエンジン0.24.0をローカルで起動して以下を実行します。
Python標準ライブラリのみを使い、Nemo製品UUID・バージョン・音声IDを照合します。

```bash
python3 scripts/generate-audio.py --sample
python3 scripts/generate-audio.py
```

試聴は`audio/02.wav`（観自在菩薩）。利用規約の確認は[音声ライセンス記録](docs/audio-license.yaml)を参照。
音声の利用・二次配信は[VOICEVOX Nemo利用規約](https://voicevox.hiroshiba.jp/nemo/term/)に従ってください。
音声クレジット: **VOICEVOX Nemo**。

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
Aは現行WAVのPCMをそのまま連結、BはNemo男声1で現行と同じ読みと語の区切りを保ち、母音長と音高のばらつき・抑揚・節間を抑えた調整案です。
本体の29節・予約再生・速度設定は変更していません。比較音声は1.0倍で再生します。
自然さや読みの聞き取りやすさは試聴で判断し、全節への適用はその後に決めます。
Bは節を個別生成して連結するため、節境界のピッチや息継ぎの連続性までは保証しません。

```bash
python3 scripts/generate-audition.py --engine http://127.0.0.1:50121
python3 scripts/check-audition.py
```

`audition/manifest.json`に5節の読み・生成query・設定・hashを保存します。比較用WAVとHTML/CSS/JSだけを公開し、manifestと生成スクリプトは配信しません。
元の音声生成スクリプトの`--sample`は既存の`audio/02.wav`を上書きするため、この比較版生成には使いません。
