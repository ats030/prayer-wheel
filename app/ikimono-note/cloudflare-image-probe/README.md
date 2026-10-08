# Python WorkersのJPEG/PNG検証

`pillow-heif` を除いたPillow単独のローカル検証です。本番へデプロイしないでください。
秘密・利用者データ・本番モジュールを読みません。入力は合成画像だけです。
既存の `docs/tool-license-python-workers-probe.yaml` の条件を適用します。
Workerの収集対象は `src` に限定し、仮想環境と検証スクリプトは含めません。

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

Wrangler dry-runも成功し、未圧縮11595.15 KiB、gzip 3091.58 KiBでした。
2026-10-08確認の[公式制限](https://developers.cloudflare.com/workers/platform/limits/)は
Freeも未圧縮64 MiB、圧縮サイズ制限なしです。容量上限は超えていませんが、
CPU 10 ms、メモリ128 MB、起動時間の検証は残っています。

これは `pillow-heif` のwheel不足とPillow全体の不適合を区別する検証です。
HEIC、GPS、実写真、画質判定、CPU/メモリ、公開環境、Workers Freeへの適合は未検証です。
ブラウザでHEICをJPEG化した後に既存Python画像処理を再利用できる可能性を示しますが、
本番構成としての採用はまだ決めていません。

公式資料: [Python packages](https://developers.cloudflare.com/workers/languages/python/packages/)。

## 既存画質判定・ZIP処理と負荷の追加検証

`prepare_reference.py` は現在の `image_quality.py` と `photo_archive.py` を
隔離したsrcへコピーし、vision.pyからprepare_imageだけをASTで抽出します。
本番アプリ全体、設定、認証、秘密、利用者データは読みません。
コピーしたコードはGit対象外で、入力は合成JPEGとZIPだけです。
source hashをレスポンスに含め、検証で参照コードとの一致をassertします。

```sh
/home/ats030/.venv/bin/python prepare_reference.py
PATH="$PWD/.venv/bin:$PATH" uv run pywrangler dev --port 8790
```

別端末で実行します。

```sh
python3 check_reference.py
/home/ats030/.nvm/versions/node/v24.19.0/bin/node profile.mjs
```

profile.mjsはNode 24のfetchとdekitaの既存Playwright内のwsを使用します。
デフォルトのinspectorポート9229を使うため、他のWorkers検証を同時に起動しません。

2026-10-08に、大きな写真、小さな写真、暗い写真、鮮明な模様の4条件で
画質判定結果（測定値・警告・拒否）がネイティブPythonと一致しました。
各条件を3回確認しています。ZIPは3条件に加えて鮮明な模様でも原本のSHA-256と
MIME・ファイル名が一致しました。複数写真、親パス、壊れたZIPは拒否しました。

2000×1200のJPEGでは、ウォーム実行の画質判定は約104～122 ms、
縮小・JPEG化は約152～161 msでした。小さい180×120でも画質判定は16～17 msです。
鮮明な模様の画像処理に対するローカルV8サンプリングは、idleを除いて
271.205 / 275.353 / 275.815 msでした。これらはローカルのサンプル・経過時間であり、
Cloudflare本番のリクエストCPU課金計測値や上限の直接検証ではありません。

[FreeのCPU上限は10 ms](https://developers.cloudflare.com/workers/platform/limits/)です。
ローカル実測から、画像処理をそのままWorkersへ残す案は負荷が大きく、
無料運用として採用する根拠が不足しています。ブラウザ側のHEIC/ZIP/縮小を優先して
検証し、画質判定と識別品質を維持できるかを確認します。
公開環境、実写真、全ZIP条件、巨大画像・同時要求・メモリ上限は未検証です。
