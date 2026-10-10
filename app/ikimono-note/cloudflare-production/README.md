# 本番Workerの接続とログイン不要の利用

2026年10月10日（日本時間）、課題 `ats030-paskw`。
利用者の「本番Workerではログイン不要」という指定に合わせ、本番URLの通常利用を公開した。
旧サイトからの転送・停止は行っていない。全経路の無料枠適合と移行完了は未確認である。

| 対象 | 配備済みの値 |
| --- | --- |
| 入口 | https://ikimono-note.ats030.workers.dev / `2c452d51-2fed-4f62-b747-4aaffa6ea252` |
| 非公開Python | `ikimono-note-backend` / `41eea04f-0b76-417a-8c42-336fab58e580` |
| D1 | `ikimono-note-production-candidate` / `35c18d62-4de8-4c50-96eb-14b7d3e9e6d5` |
| 入口ソースSHA256 | `ad6c431a9c22570631e5f2b9e24852e8d05c9a87d3dde28bdcf4903cbe687ec9` |

## 初回利用とアクセス解析（ats030-8pa4l）

未設定の利用者に「利用の準備」を表示し、`/settings?setup=gemini` の簡単設定へ案内する。
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
ローカルの対象ソースと本番配信の両方で通過。合成キーだけを使い、識別API・Google/Driveには接続しない。
本番配信のテストでも設定APIとログイン状態は公開設定の合成応答に固定し、外部通信とPOSTを拒否する。

```sh
cd ..
/home/ats030/.nvm/versions/node/v24.19.0/bin/node tests/check_onboarding.mjs --live
```

引数なしなら対象HTML/CSS/JSをローカルから読む。設定JSONを第1引数で指定でき、指定がなければ
本番の公開設定を1回だけ読む。ブラウザからの実Googleログイン・Drive保存・実AI識別を証明するテストではない。
mediumレビューのprovider上書き・保存失敗時の保存期間復元の指摘を修正し、提供ソースの再レビューは指摘なし。
既存のAI選択表示が既定値のままになる不具合も、同じ設定経路で再現して修正した。
プライバシー説明に残る旧環境の認証・ホスティング記述は別課題 `ats030-tlv7j` で扱う。

## 認証の範囲

両Workerで `IKIMONO_LOGIN_REQUIRED=0` を明示し、Basic認証と通常利用のGoogleログイン要求を外した。
撮影・設定・履歴・地図・識別の許可リストだけを未ログインで通す。共有作成・取り消し・
アカウント操作にはGoogleログインと所有者確認を残す。公開版のサーバー設定変更は403のまま。
Drive連携はブラウザ側で別途Googleの許可を得る。AIは利用者自身のAPIキーを使い、運営者の試用枠は有効にしない。

設定の省略・誤った値は従来の認証必須に戻る。検証版の配備・認証は変更していない。
公開版モード、Host制限、CSP、入力上限、識別の利用制限を維持する。
全移行完了までnoindexと自動保存ログ無効を維持する。Googleクライアントは任意のログインとDrive用に残す。
本番のセッション鍵は検証版と分離する。秘密はGit外の
`/var/tmp/ikimono-cloudflare-production-private/secrets.json` に0600で保管し、内容を出力しない。
このローカル保存先はOS清掃・端末故障への保証を持たない。

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

## 確認結果

実URLへの認証情報なしの要求で撮影・設定・履歴・地図・設定API・更新履歴が200。
共有・アカウント操作は401、サーバー設定変更は403。
`check.py` は両SHA、全assetsと対応ソース、OAuth開始・不正state拒否、入力上限、
移行済み共有ページと写真全バイト/MIMEを確認し通過した。実データへの書込みは行っていない。
関連pytest33件とJavaScriptのゲスト利用・従来認証・識別契約検査も通過した。

mediumの差分レビューで、ゲスト検査が不要なBasicパスワードを要求する指摘を修正し、
パスワードなしでもセッション鍵の分離を確認する回帰テストを追加した。
レビューは秘密を除いた提供差分・対象ソースに限定される。実ビルド・配備・HTTP検査は別に実施した。
検証版は未認証401・認証後health200で以前のSHAを維持し、旧Cloud Run healthも200。
Googleクライアントの新URL登録は利用者から完了報告がある。実アカウントでの新URLへのログイン完了と
Drive保存・読み戻しはこの自動検査では行っていない。

## 残件と切戻し

[本番移行手順](../docs/cloudflare-production-rollout.md)の無料枠、差分データ、Drive全写真、
旧共有URLの継続は未完了。大きい識別入力と併用・他AIなどのCPU超過・未計測を解消するまで、
旧サイトからの転送・停止や完全移行を完了扱いしない。有料プランへ変更していない。

初回導線だけを切り戻す場合もGoogle Analyticsの停止を維持し、ソースを修正して両Workerを再配備する。
過去のGA有効版へそのまま戻さない。

認証を戻す場合は両configを `IKIMONO_LOGIN_REQUIRED=1` にしてバックエンド→入口の順に配備する。
専用Basicパスワードは切戻しのため保管したまま。停止が必要なら入口の `workers_dev=false` を配備する。
D1・Firestore・Drive・検証版は削除しない。入口だけ以前のSHAへ戻すとhealthが整合しないため、
必ず整合する両Worker版を揃える。
