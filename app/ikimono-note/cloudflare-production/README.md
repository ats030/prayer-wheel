# 本番Workerの接続とログイン不要の利用

2026年10月10日（日本時間）、課題 `ats030-paskw`。
利用者の「本番Workerではログイン不要」という指定に合わせ、本番URLの通常利用を公開した。
旧サイトからの転送・停止は行っていない。全経路の無料枠適合と移行完了は未確認である。

| 対象 | 配備済みの値 |
| --- | --- |
| 入口 | https://ikimono-note.ats030.workers.dev / `706b1211-8bc3-47df-b87f-b2005c442b2e` |
| 非公開Python | `ikimono-note-backend` / `9f3a999a-b3b2-4df7-9ab0-1172c0d32f40` |
| D1 | `ikimono-note-production-candidate` / `35c18d62-4de8-4c50-96eb-14b7d3e9e6d5` |
| 入口ソースSHA256 | `ecec30fbc80e3f1bb864e66d54e3c13f8d54937ca87735a19ed9136071e11561` |

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

認証を戻す場合は両configを `IKIMONO_LOGIN_REQUIRED=1` にしてバックエンド→入口の順に配備する。
専用Basicパスワードは切戻しのため保管したまま。停止が必要なら入口の `workers_dev=false` を配備する。
D1・Firestore・Drive・検証版は削除しない。入口だけ以前のSHAへ戻すとhealthが整合しないため、
必ず整合する両Worker版を揃える。
