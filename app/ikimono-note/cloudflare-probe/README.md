# Cloudflare適合検証

公開版の依存がPython Workersへ持ち込めるかを確認する、隔離したローカル検証です。
本番アプリ、環境変数、認証情報、利用者データは読みません。AI APIも呼びません。
このディレクトリを本番としてデプロイしないでください。

## 再現手順

Node.js 22以上とuvを使い、このディレクトリで実行します。

```sh
uv sync
PATH="$PWD/.venv/bin:$PATH" uv run pywrangler dev --port 8788
```

workers-py 1.17.7はuv 0.12.3以上が必要です。検証用のuvをdev依存に固定し、
マシン全体のuvは変更しません。初回はPyodideの公式実行環境をダウンロードします。

## 2026-10-07の結果

依存解決で失敗しました。WorkersのPythonはWebAssembly版の依存を要求し、
`pillow-heif==1.7.0`には利用できるwheelがありませんでした。

```text
Because pillow-heif==1.7.0 has no usable wheels and
ikimono-note-cloudflare-probe depends on pillow-heif==1.7.0,
we can conclude that your requirements are unsatisfiable.
```

実行条件はPython WorkersのCPython 3.14.2 Emscripten、Pyodide index 314.0.7、
workers-py 1.17.7、workers-runtime-sdk 1.9.3、uv 0.12.3です。
これは現行依存をそのまま移せないという結果です。ブラウザ側へHEIC処理を移す案の
成否、JPEG/PNG処理、CPU時間、無料枠内の運用を検証済みと扱ってはいけません。

2026-10-08に画像依存を分離して追加検証しました。
[HTTP検証](../cloudflare-http-probe/README.md)では同期・非同期httpx、POST、multipart、
FastAPI同期ルートとSDKによる同一スレッド内のthreadpool呼出しが成功しました。
[画像検証](../cloudflare-image-probe/README.md)ではPillow単独のJPEG/PNG、撮影日時、
向き補正、縮小、JPEG化、EXIF除去が成功しました。いずれもローカルWorkersだけの結果です。
`pillow-heif`の不適合は残りますが、同期HTTP・Pillow全体の置き換えを必須とはしません。

## 移行を続けるために必要な確認

- ブラウザ側のHEICデコード、EXIF取得、ZIP読み込み、縮小・EXIF除去、画質チェック。
  Android/PC/iOSの実機と写真で、現行結果との差を確認します。
- 公開WorkersでのHTTP、Googleログインとセッション検証、ユーザー・共有データの保存。
  永続ローカルファイル・直接のスレッド生成・GCPメタデータ認証に依存する箇所は変更が必要です。
  SDKのthreadpool互換処理はCPU処理を並列化しません。識別ジョブの状態と寿命も検証が必要です。
- 共有ページと写真、広告、地図の照会、利用者のローカルOllama連携を含む既存APIの検証。
- Cloudflare接続とFreeプランは利用者確認済み。D1権限は未付与です。
  ikimono-noteの標準URL決定後にGoogle OAuthの登録を追加します。
- 旧サイトの記録をGoogle Driveへ保存し、新サイトで写真付き記録を読み込む確認。
  APIキーは移行しません。同期未完了の写真や未接続端末の記録を確認するまで旧サイトを停止しません。
- Firestoreのユーザー・共有情報の移行と、既存共有URLの扱い。
  旧run.app URLはCloud Run停止後に維持できません。共有URLの利用状況と案内期間は切替前に確認します。
- 無料枠の実測と上限時の表示。基盤が返すエラーではアプリの案内を返せない場合も検証します。

ここに列挙した内容は検証条件です。進捗・判断はBeads issue `ats030-paskw`へ記録します。
本番の停止、有料プランへの切り替え、機能削減は行っていません。

公式資料:
[Python packages](https://developers.cloudflare.com/workers/languages/python/packages/)、
[FastAPI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/)、
[Workersの制限](https://developers.cloudflare.com/workers/platform/limits/)。
