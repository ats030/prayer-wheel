# 本番候補Workerの接続

2026年10月10日（日本時間）、課題 `ats030-paskw`。
本番候補D1を実際のWorkerへ接続した。一般公開への切替は未実施。

| 対象 | 配備済みの値 |
| --- | --- |
| 入口 | https://ikimono-note.ats030.workers.dev / `78e3cbcc-8151-4a01-b379-76e2333d0dcb` |
| 非公開Python | `ikimono-note-backend` / `52ea1047-6ca2-4ce2-bba9-0a63b3da76f7` |
| D1 | `ikimono-note-production-candidate` / `35c18d62-4de8-4c50-96eb-14b7d3e9e6d5` |
| 入口ソースSHA256 | `d02c2839f0e15bacdd6c4ff24dee5fbd95191868aec90b4b3eff7d18e9e56be9` |

既存のレビュー済み検証版コードを使い、Basic認証とnoindexを維持する。
本番候補のパスワード・セッション鍵は検証版と別にし、同じGoogleクライアントを使う。
秘密はGit外の `/var/tmp/ikimono-cloudflare-production-private/secrets.json` に0600で保管する。
ローカル保存先はOS清掃・端末故障への保証を持たない。秘密の保全方法は公開前に確定する。
両Workerの自動保存ログを無効にし、共有tokenを含むURLを保存しない。

## ビルドと配備

Wranglerのcustom buildは実行ディレクトリに依存するため、以下はこのディレクトリから実行する。
`build.py` は既存のallowlistビルダーを使い、固定済み依存関係をconfigのルートへ参照する。
依存ライブラリの更新・新規インストールは行わない。

```sh
python3 ../cloudflare-preview/run_wrangler.py deploy --config backend.jsonc \
  --secrets-file /var/tmp/ikimono-cloudflare-production-private/secrets.json
python3 ../cloudflare-preview/run_wrangler.py deploy --config front.jsonc \
  --secrets-file /var/tmp/ikimono-cloudflare-production-private/secrets.json
```

Pythonは外部URL・preview URL・routesを持たず、入口の固定Service Bindingでだけ呼ぶ。
DB・allowed hosts・public originは入口とPythonで揃える。既存検証版の配備は変更しない。
共有する生成物は実行時に変数へ依存するコードを持ち、各Workerのorigin設定と秘密を起動時に適用する。
生成物の更新を別の配備成功と同義にせず、配備後に両ソースSHAと実bindingを検査する。

## 確認結果

`check.py` は秘密の分離、認証、配備SHA、対応ソース、設定、OAuth開始・不正state拒否、
診断経路の非公開、入力上限と、移行済み共有ページ・全写真バイト/MIMEを確認する。
実利用者のセッションを作ったり、記録・共有・利用者情報を書き換えたりしない。

```sh
/home/ats030/.venv/bin/python check.py
```

検査はすべて通過した。D1全列の独立した再照合も通過し、利用者2件・共有1件・写真28,200 bytesを維持する。
Cloudflare APIで両WorkerのD1 IDとService Binding、Python外部URL無効を確認した。
検証版のDBは従来の `779b52d2-66f6-4f29-8a4b-7f268fdc85d9` のまま。
検証版health・旧Cloud Run healthは200。
関連pytest29件とJavaScript入口の認証・転送契約検査が通過した。

初回配備は依存関係の探索先が違い、workers SDKを見つけられず10021になった。
既存依存ツリーを新configルートへ参照して修正し、実配備成功で確認した。
共有検査の初回HTTP403はUser-Agent条件の差だった。同一URL・同一認証で既存検査のUser-Agentは200。
検査プログラムを既存検査と同じ条件に揃え、全体の再実行が通過した。

mediumレビューの秘密使い回し検査不足は修正済み。追加レビューはbwrapで読取不能だったため、
対象コードを直接渡したmediumレビューで確認した。そのレビューは参照先の既存ビルダーを含まず、
追加された対象コードだけでは指摘なしという限定結果。参照先を含む実ビルド・配備・HTTP検査は別途通過した。

## Google設定と公開前の条件

利用者から新URLの登録完了報告がある。Googleへの認証開始要求は302でGoogleのログインへ進み、
OAuthエラー経路・redirect_uri_mismatchは検出されなかった。実アカウントのログイン完了・
トークン交換・Drive接続は今回の自動検査では行っていない。

既存の[Google認証クライアント](https://console.cloud.google.com/auth/clients)に、
旧URL・検証版を残したまま次の値を追加する。

| 項目 | 値 |
| --- | --- |
| 承認済みリダイレクトURI | `https://ikimono-note.ats030.workers.dev/auth/callback` |
| 承認済みJavaScript生成元 | `https://ikimono-note.ats030.workers.dev` |

設定根拠は[サーバー側OAuth](https://developers.google.com/identity/protocols/oauth2/web-server#creatingcred)と
[ブラウザ側OAuth](https://developers.google.com/identity/oauth2/web/guides/get-google-api-clientid)。
本番公開には[本番化手順](../docs/cloudflare-production-rollout.md)の無料枠・差分データ・
Drive全写真・旧共有URL・公開設定を確認する。特に、大きな入力でのCPU超過と未検証経路を残したまま
Basic認証を外さない。Google登録だけでは公開条件を満たさない。

## 切戻し

旧サイトへの案内を維持する。候補URLを停止する必要があれば、入口の `workers_dev` をfalseにして配備する。
DB・旧Firestore・Drive・既存検証版を削除しない。一般公開用の認証解除はこの構成に実装していない。
公開版更新履歴は未公開の移行を完了済みとして記載せず、一般公開の変更と同時に配信する。
