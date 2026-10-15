# 浄財による開発支援

フッターに「浄財」ボタンを準備していますが、支援の受け付けは始まっていません。
`support-config.json`のURL未設定時は非表示です。公開ビルド時に設定を読み、
HTMLの外部リンクとして出力します。アプリに決済SDKや決済状態は追加しません。
ソースのindex.htmlを直接配信する場合は非表示のままです。

## 支援先の候補と未確認事項

第一候補はBuy Me a Coffeeです。支援者の登録不要を優先します。
日本は入金対象国ですが、Stripe規約も適用されるため、返礼なしの個人開発支援に
使えるとはまだ判断できません。確認記録は[利用条件](support-license.yaml)です。
初回入金時の審査が案内されており、登録だけで受け取りを保証するものではありません。

問い合わせ文の案（未送信）:

> I am an individual developer based in Japan. I maintain a free browser app
> called prayer-wheel, which displays Buddhist sutra text with synthesized
> recitation. I would like to accept optional, one-time support for its
> development and hosting, without rewards, products, or paid access.
> Is this use eligible for Buy Me a Coffee and its Stripe Standard Connect
> payouts in Japan, given Stripe's restriction on donations to individuals?
> Please also confirm the fees and supported payment currencies for this use.

## 支援ページの説明文案

prayer-wheelは、マニ車を回しながら般若心経の文字と音声を楽しめる無料のアプリです。
いただいた支援は、このアプリの開発と運営に使います。
支援は任意です。支援の有無や金額によって、使える機能は変わりません。

## 公開時の設定

1. 提供者から用途への対応を確認し、必要な本人・銀行情報の登録を終えて支援ページを公開します。
2. 確認結果を`docs/support-license.yaml`に記録し、`support-config.json`の`url`へ実際のHTTPS URLを設定、`usageConfirmed`を`true`にします。
3. 通常の公開ビルドと検証を実行してデプロイします。URLありで用途未確認の場合、ビルドは失敗します。

支援先は別タブで開き、読経画面を残します。受け付け停止時はURLを`null`へ戻して
再ビルド・デプロイすれば、ボタンを非表示に戻せます。
個人情報や秘密鍵は設定ファイルに記録しないでください。

検証:

```bash
python3 scripts/check-support.py
python3 scripts/check-support.py --url http://127.0.0.1:8743
```

ブラウザ検証では支援リンクを一時的に表示して、外部サイトへの決済は行わず、
320px・1280pxの表示とキーボード操作を確認します。
