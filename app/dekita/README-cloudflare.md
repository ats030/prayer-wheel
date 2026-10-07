# Cloudflare 移行（準備中）

Cloudflare Workers Static Assets の無料標準URLへ配信する構成です。
2026-10-07時点では公開・スコア移行の確認は未完了です。Cloud Runは停止しません。

## ビルドと検証

Node.js 22以上、Wrangler 4.148.0、Python 3を使います。

```sh
python3 scripts/build-cloudflare.py
npx wrangler@4.148.0 deploy --dry-run
npx wrangler@4.148.0 dev --port 8787
```

別の端末で`node scripts/check-cloudflare.mjs`を実行すると、6つのゲームの起動、
音声配信、開発ファイルの非公開、スコア引き継ぎ、不正ファイルの拒否を確認できます。
既存のPlaywright依存とChromiumを使用します。公開URLも引数で指定できます。

`dist`だけを配信します。テスト、依存ライブラリ、Docker設定、秘密情報は含めません。
配信するJS・音声は既存ゲームのものです。
静的ファイルは無料・回数無制限ですが、アカウントのWorkers Freeプラン確認が必要です。
有料プラン、独自ドメイン、有料機能をこの作業で追加しません。

## 公開とハイスコア引き継ぎ

1. Cloudflareの認証とFreeプランを確認し、`npx wrangler@4.148.0 deploy`で公開します。
2. 旧Cloud Runにも`migration.html`と`migration.js`を配信します。旧URLの`/migration.html`を、ゲームで使っていた端末・ブラウザから開き、ハイスコアを保存します。
3. 新URLの`/migration.html`で保存したJSONを読み込みます。既存スコアより低い値では上書きしません。
4. 新URLで6つのゲームと音声、引き継いだハイスコアを確認します。
5. 移行確認後に、旧URLの案内とCloud Run停止・不要イメージ整理を進めます。

ブラウザに残るスコアを運営者が遠隔で一括回収することはできません。
旧URLを停止すると、そこへアクセスしての書き出しができなくなります。
引き継ぎの確認と案内期間が終わるまでは停止しません。
Dockerfile/cloudbuild.yamlのコピー対象に`migration.html`、`migration.js`を追加済みです。
旧サイトへの配信は未実行です。

既存のvisit-logタグはローカル運営環境向けHTTP URLです。公開HTTPSでは読み込めません。
今回そのタグやCSPの変更、代替分析サービスの追加は行っていません。
無料移行の料金・利用条件は`docs/tool-license-cloudflare.yaml`に記録します。
