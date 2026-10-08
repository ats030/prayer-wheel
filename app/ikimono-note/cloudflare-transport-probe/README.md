# 写真送信データのCPU検証

ブラウザで用意した送信JSONを、Workerがネイティブストリームで転送する方式を検証します。
実AIへのHTTP送信、Google接続、DB操作、利用者データの読み取りは実装していません。
元のPython関数からGeminiのプロンプトと生成設定を取り出し、seed=3の合成写真だけを使います。
写真1枚は1,997,593 bytesで、1枚と3枚の両方を比較します。

本番CPU会計では、写真をWorker内でbase64とJSONへ変換すると1枚23〜49ms、3枚66〜102msでした。
ブラウザ側で組み立てたJSONのネイティブ転送は、1枚と3枚それぞれ6要求すべて0msという記録になりました。
0msはCPU会計の表示値で、計算量が厳密にゼロであることを示しません。
30件すべてのtail、HTTP200、送信JSONとのSHA一致、実行ソースSHAの一致を確認しました。
認証はこの検証用のBasic認証だけで、本体のGoogle認証、写真入力検証、識別後処理は含みません。
本体への組み込みとアプリ全体の無料適合は未完了です。

比較条件と縮約記録は[本番計測記録](../docs/cloudflare-preview-production-evidence.md)にあります。
Pythonから途中でJavaScriptへ変換する案は遅くなったため採用していません。
この案もローカル診断に残し、同じ条件で再検証できるようにしています。

## ローカル検証の再現

この計測ではNode24.19.0、Wrangler4.149.0、既存のPlaywright inspector clientを使いました。
Pythonの依存は既存probeと同じです。
新しい依存を追加していません。
Wranglerキャッシュはpywranglerのnpx起動で更新されるため、版の固定は別issue `ats030-g1gd1` で扱います。

1. `../cloudflare-app-probe` で `python3 build.py` と `/home/ats030/.venv/bin/python prepare_profile.py` を実行します。
2. 同probeを `dev --port 8793 --inspector-port 9229` で起動します。
3. このディレクトリの `wrangler.jsonc` を使い、同じWrangler版で `dev --port 8794 --inspector-port 9230` を起動します。
4. `/home/ats030/.nvm/versions/node/v24.19.0/bin/node profile.mjs > /tmp/transport-local.jsonl` を実行します。

ビルドは起動時に `_digest.mjs` を生成します。
両方のWorkerのソースSHAが現在のソースと一致しない場合、計測を拒否します。
HTTP待機とinspector操作にはタイムアウトがあり、失敗時はinspector計測を停止します。
各条件を20要求ずつ5回測り、短い処理を1回のサンプルだけで評価しません。
このサンプル値にはローカルランタイムの匿名処理などが含まれ、本番CPU会計値へ換算できません。
ローカルの `/wire` は開発用中継のbody再利用エラーを避ける変換ストリームを使い、遠隔のネイティブ転送とは異なります。

## 認証付き一時Workerの再現

一時URLは `https://ikimono-note-transport-preview.ats030.workers.dev` です。
測定後に `workers_dev: false` へ戻し、外部アクセスを停止しました。
元アプリの検証版を置き換える設定ではありません。
この転送診断を、本体の入力検証を省略したAIプロキシとして使うことはできません。

再測定時は `node prepare_remote.mjs` で元のプロバイダーのソースSHAと照合した合成入力を作ります。
秘密値はGitへ入れず、既存の検証パスワードだけを0600の秘密ファイルへ渡します。
一時Workerの `workers_dev` を測定中だけ有効にしてデプロイし、`python3 check_public.py` で境界を検査します。
`python3 measure_remote.py --samples 5 --output /tmp/transport-remote.json` で本番CPUを記録します。
欠測、HTTP失敗、版不一致、ソース不一致、バイト不一致、runtime回数の逆順は比較不適格として終了コード2になります。
計測後は `workers_dev: false` で再デプロイし、一時秘密ファイルを削除します。

ローカルの `node check_remote.mjs` は認証、Host、不許可URL、通常応答のruntime識別子非露出、転送バイトの一致を検査します。
Node24にはWorkersの `Uint8Array.toBase64()` がないため、この機能だけテスト用のshimを使います。
CPU会計の測定はshimを使わない実Workersで行います。

今回の変更は運営者用の隔離診断で、本体の利用者向け動作を公開していないため、更新履歴の対象外です。
