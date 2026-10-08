# Python Workers HTTP互換性検証

画像依存を除き、既存APIで使うHTTPとFastAPIの実行方式を比較するローカル専用検証です。
本番アプリ・秘密・利用者データを読みません。デプロイしないでください。
既存の `docs/tool-license-python-workers-probe.yaml` のローカル検証条件を適用します。

## 再現

Node.js 22以上とuvを使い、このディレクトリで実行します。

```sh
uv sync
PATH="$PWD/.venv/bin:$PATH" uv run pywrangler dev --port 8788
```

別端末で合成データの送信先を起動します。

```sh
python3 echo.py
```

第三の端末で検証します。

```sh
python3 check.py
```

GETの送信先は固定の `https://example.com/`、POSTは `127.0.0.1:8789` です。
POSTの写真は画像ではなく `synthetic-photo` というダミー文字列です。
echoサーバーはloopbackだけにbindします。依存・仮想環境・生成物はGit対象外です。
Workerの収集対象は `src` です。仮想環境やcheck/echoをWorkerへ含めません。

## 2026-10-08の実測

Wrangler 4.148.0、workers-py 1.17.7、workers-runtime-sdk 1.9.3、
Pyodide 314.0.7、CPython 3.14.2 Emscripten、httpx 0.28.1、
FastAPI 0.136.1、Starlette 1.7.0、AnyIO 4.15.1で確認しました。

| 試験 | ローカルWorkersの結果 |
| --- | --- |
| httpx.Clientの同期HTTPS GET | HTTP 200、本文確認成功 |
| httpx.AsyncClientの非同期HTTPS GET | HTTP 200、本文確認成功 |
| 同期JSON / form / multipart POST | Content-Typeと合成本文の到達確認成功 |
| FastAPIの同期defルート | HTTP 200 |
| starlette.run_in_threadpool | 呼出し完了 |
| threading.Thread.start | RuntimeError: can't start new thread |

SDKの `_workers_sdk_package_patches.py` は `anyio.to_thread.run_sync` を
同一スレッド内の呼出しに置き換えています。threadpoolの成功はOSスレッドの存在や
CPU処理の並列実行を示しません。直接のスレッド生成は失敗することも確認しました。

Wrangler dry-runも成功し、未圧縮8844.16 KiB、gzip 2190.88 KiBでした。
2026-10-08確認の[公式制限](https://developers.cloudflare.com/workers/platform/limits/)は
Freeも未圧縮64 MiB、圧縮サイズ制限なしです。バンドル容量が上限以下でも、
FreeのCPU 10 msとメモリ128 MBの適合を確認したことにはなりません。

この結果から、既存同期HTTPとFastAPI同期ルートの全面非同期化を必須とする根拠は
なくなりました。ただし実際のOAuth、各AI API、HTTPエラー・timeout・redirect、
大きな写真、同時要求、Workers FreeのCPU/メモリ上限、公開環境は未検証です。
localhostへのPOST成功は外部APIへのmultipart成功を保証しません。

移行で依然変更が必要な箇所は、pillow-heif、GCPメタデータ認証、永続ローカル保存、
識別ジョブのメモリ状態とリクエスト終了後の寿命です。
本番切替や無料運用の成立を確認した結果ではありません。

公式資料: [Python packages](https://developers.cloudflare.com/workers/languages/python/packages/)、
[FastAPI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/)。
