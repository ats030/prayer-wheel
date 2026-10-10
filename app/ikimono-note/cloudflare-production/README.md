# 本番WorkerのGoogleログインと初回利用

2026年10月10日（日本時間）、課題 `ats030-paskw`。
利用者の最新の指定に合わせ、本番URLの通常利用はGoogleログイン必須に変更した（課題 `ats030-rgmf5`）。
旧サイトからの転送・停止は行っていない。全経路の無料枠適合と移行完了は未確認である。

| 対象 | 配備済みの値 |
| --- | --- |
| 入口 | https://ikimono-note.ats030.workers.dev / `4ada42d5-b03b-4df9-8689-b0369f0dec0e` |
| 非公開Python | `ikimono-note-backend` / `5aa52f0a-a55a-4706-b394-a54bcf4a2a59` |
| D1 | `ikimono-note-production-candidate` / `35c18d62-4de8-4c50-96eb-14b7d3e9e6d5` |
| 入口ソースSHA256 | `b0f4a16f89b8abe821e60e5ffcaa5f03a4244fb7e504210c4254c1bf2da3cc52` |

## 初回利用とアクセス解析（ats030-rgmf5 / ats030-8pa4l）

未ログインは `/login` へ303で案内する。Google認証後は `/login?continue=1` でブラウザ内の設定を確認し、
AI設定済みなら撮影へ、未設定なら `/settings?setup=gemini` の簡単設定へ案内する。
既存の他AI設定や壊れた保存値がある場合は通常設定へ進み、値を上書きしない。
設定読込みに失敗した場合は入口で説明し、通常設定へのリンクを出す。
記録は端末内、Driveは任意。ログインだけでは同期や端末内データのアカウント分離は行わない。
ログイン画面と記録画面で、このブラウザに保存される範囲を明記する。
本番の既定AIがGeminiのときにだけ簡単設定を使い、Geminiキーと保存期間の選択を既存の
ブラウザ保存処理で保存する。provider・modelsは書き換えない。他AIや既存設定があれば通常設定を使う。
保存成功後は撮影へ戻り、失敗時は保存期間の選択を復元して、その場で再試行を案内する。

Google AnalyticsはHTMLに挿入せず、同意画面を廃止した。以前に同意していても動作しない。
以前開いたページが使うanalytics asset URLは、解析機能を持たないファイルを返す。
CSPからGAのscript/connect許可だけを外し、Google認証・Drive・Geminiの通信許可は維持する。
既に古い解析コードを実行中のタブには、新しいページへの再読込みが必要である。
旧Cloud Run・検証版はこの作業では再配備していない。変更は本番Workerに反映した。

Chromiumの390px/1280pxで、初回導線、キーボード、端末/タブ保存、既存/別タブのAI選択、
書込み失敗時の復元、設定読込み失敗、以前の解析同意がある場合を確認した。
この前段の初回設定作業（ats030-8pa4l）では、ローカルの対象ソースと当時の本番配信の両方で通過。
合成キーだけを使い、識別API・Google/Driveには接続しない。
本番配信のテストでも設定APIとログイン状態は公開設定の合成応答に固定し、外部通信とPOSTを拒否する。

```sh
cd ..
/home/ats030/.nvm/versions/node/v24.19.0/bin/node tests/check_onboarding.mjs /tmp/ikimono-public-settings.json
/home/ats030/.nvm/versions/node/v24.19.0/bin/node tests/check_login_onboarding.mjs /tmp/ikimono-public-settings.json --live
```

引数なしなら対象HTML/CSS/JSをローカルから読む。設定JSONを第1引数で指定でき、指定がなければ
本番の設定を1回だけ読む（現在は要ログインのため、保存済みの検証用JSONを指定する）。ブラウザからの実Googleログイン・Drive保存・実AI識別を証明するテストではない。
mediumレビューのprovider上書き・保存失敗時の保存期間復元の指摘を修正し、提供ソースの再レビューは指摘なし。
既存のAI選択表示が既定値のままになる不具合も、同じ設定経路で再現して修正した。
プライバシー説明に残る旧環境の認証・ホスティング記述は別課題 `ats030-tlv7j` で扱う。

## 認証の範囲

両Workerで `IKIMONO_LOGIN_REQUIRED=1`、`IKIMONO_PREVIEW_BASIC_REQUIRED=0` を明示する。
Googleログインは必須、検証版専用のBasic認証は本番には要求しない。
撮影・設定・記録・地図は未認証303、保護APIは401。共有ページと写真、法務情報、assetsは公開のまま。
公開版のサーバー設定変更はログイン後も403。Driveは別途Googleの許可を得る。
運営者の試用枠は無効のまま。セッション鍵やOAuthクライアント、D1は変更しない。

新しいBasicフラグを省略した既存の検証版は、従来どおりBasic認証を維持する。
検証版・旧Cloud Runはこの作業では再配備しない。Host制限、CSP、入力上限、利用制限を維持する。

## ビルドと配備

このディレクトリから実行する。既存のallowlistと固定依存関係を再利用するが、
本番の生成コード・assets・SHA・更新履歴は本番ディレクトリへ独立して生成する。
検証版の生成物・配備SHAを上書きしない。依存ライブラリの追加・更新は行わない。

```sh
python3 ../cloudflare-preview/run_wrangler.py deploy --config backend.jsonc \
  --secrets-file /var/tmp/ikimono-cloudflare-production-private/secrets.json
python3 ../cloudflare-preview/run_wrangler.py deploy --config front.jsonc \
  --secrets-file /var/tmp/ikimono-cloudflare-production-private/secrets.json
/home/ats030/.venv/bin/python check.py
```

Pythonは外部URL・preview URL・routesを持たず、入口の固定Service Bindingだけで呼ぶ。
入口とPythonのD1・Host・origin・認証設定を揃え、healthの両SHAを照合する。

## 検査の範囲

`check.py` は未認証のページ転送・API拒否・Basicプロンプトなし、両SHA、全assetsと対応ソース、
OAuth開始・不正state拒否、入力上限、移行済み共有ページと写真全バイト/MIMEを検査する。書込みはしない。

`tests/check_login_onboarding.mjs` は390px/1280pxで初回と既存設定、タブ内キー、Ollama、
壊れた保存値、ログイン失敗と設定読込み失敗を確認する。Google成功は合成応答で再現する。
`--live` は本番の入口HTMLと公開assetsを読み、認証済みの画面は対象ソースを返す。
設定・ログイン状態も合成応答を使い、外部通信とPOSTを拒否する。実アカウントの代理ログインはしない。
実Google認証の成功・Drive保存・実AI識別を証明する検査ではない。

## 今回の確認結果（ats030-rgmf5）

本番の `check.py` は通過し、未認証ページ303・保護API401・OAuth開始と不正state拒否・
両バンドルのSHA・全公開assets・移行済み共有ページと写真全バイト/MIMEを確認した。
本番入口HTML・assetsを使う390px/1280pxの導線検査も通過した（Google成功と設定応答は合成）。
解析タグとGA向けCSP許可がないこと、同日更新履歴が公開されていることも実HTTPで確認した。
対象pytest35件、JavaScriptの既存session/Gemini契約と新しい認証分離検査、前段の設定導線を通過。
広いpytestは231件通過・6件失敗。隔離した変更前HEAD05849cf1で全6件の同じ失敗を確認し、
今回の変更から独立した `ats030-gre4e` で追跡する。medium差分レビューは指摘なし。
実アカウントのGoogleログイン完了・Drive保存・実AI識別は今回の自動検査では行っていない。

## 残件と切戻し

[本番移行手順](../docs/cloudflare-production-rollout.md)の無料枠、差分データ、Drive全写真、
旧共有URLの継続は未完了。大きい識別入力と併用・他AIなどのCPU超過・未計測を解消するまで、
旧サイトからの転送・停止や完全移行を完了扱いしない。有料プランへ変更していない。

初回導線だけを切り戻す場合もGoogle Analyticsの停止を維持し、ソースを修正して両Workerを再配備する。
過去のGA有効版へそのまま戻さない。

今回のログイン必須化を切り戻す場合は両configを `IKIMONO_LOGIN_REQUIRED=0` にし、
`IKIMONO_PREVIEW_BASIC_REQUIRED=0` を維持してバックエンド→入口の順に配備する。
入口へBasic認証を追加する場合だけ、両configの `IKIMONO_PREVIEW_BASIC_REQUIRED=1` を明示する。
専用Basicパスワードは切戻しのため保管したまま。停止が必要なら入口の `workers_dev=false` を配備する。
D1・Firestore・Drive・検証版は削除しない。入口だけ以前のSHAへ戻すとhealthが整合しないため、
必ず整合する両Worker版を揃える。
