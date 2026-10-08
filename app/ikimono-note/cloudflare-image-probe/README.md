# Python WorkersのJPEG/PNG検証

`pillow-heif` を除いたPillow単独のローカル検証です。本番へデプロイしないでください。
秘密・利用者データ・本番モジュールを読みません。入力は合成画像だけです。
既存の `docs/tool-license-python-workers-probe.yaml` の条件を適用します。

## 再現

Node.js 22以上とuvで、このディレクトリから実行します。

```sh
uv sync
PATH="$PWD/.venv/bin:$PATH" uv run pywrangler dev --port 8790
```

別端末で検証します。

```sh
python3 check.py
```

## 2026-10-08の結果

Pillow 12.2.0をCPython 3.14.2 Emscripten / Pyodide 314.0.7で依存解決し、
ローカルWorkersで実行できました。workers-py 1.17.7、runtime-sdk 1.9.3、
Wrangler 4.148.0、FastAPI 0.136.1を使用しました。

JPEGとPNGの2000×1200合成画像に撮影日時とorientation=6を埋め込み、
デコード、撮影日時取得、向き補正、960×1600への縮小、JPEG再圧縮、
出力のEXIF除去を確認しました。入力にEXIFがあり、出力では空になることをassertします。

これは `pillow-heif` のwheel不足とPillow全体の不適合を区別する検証です。
HEIC、GPS、実写真、画質判定、CPU/メモリ、公開環境、Workers Freeへの適合は未検証です。
ブラウザでHEICをJPEG化した後に既存Python画像処理を再利用できる可能性を示しますが、
本番構成としての採用はまだ決めていません。

公式資料: [Python packages](https://developers.cloudflare.com/workers/languages/python/packages/)。
