# ブラウザのHEIC・撮影情報・ZIP検証

Cloudflare移行のためのローカル専用実験です。本番アプリには組み込んでいません。
生成した合成写真だけを読み、秘密・利用者データ・外部APIを使いません。
ライセンス条件は `../docs/tool-license-browser-photo-probe.yaml` を参照してください。
依存ライブラリ、合成写真、ZIPはGitへ含めません。公開用配信物ではありません。

## 再現

既存のPillow 12.2.0、pillow-heif 1.4.0とPlaywright/Chromiumを使用します。
Node.js 24.19.0、libheif-js 1.23.5、exifr 7.1.3で確認しました。
このディレクトリで実行します。

```sh
npm install --ignore-scripts
/home/ats030/.venv/bin/python generate.py
python3 -m http.server 8791 --bind 127.0.0.1
```

別端末で検証します。

```sh
/home/ats030/.nvm/versions/node/v24.19.0/bin/node check.mjs
```

PythonとNodeのパスは検証環境のものです。別環境では同じ依存を持つ実行環境を指定します。
Playwrightは隣接するdekitaの既存依存を利用します。

## 2026-10-08の結果

- 撮影日時の数値タグ36867へのfallbackと `reviveValues: false` により、元の撮影日を保持。
  東京とロサンゼルスのタイムゾーンでも `2026-10-07` のままになることをassertしました。
- GPSを小数4桁まで保持し、緯度35.5・経度139.75の取得をassertしました。
- 8種類のEXIF orientationについて、実際のHEIF irot/imir属性を生成しました。
  元の解像度と4隅の色をネイティブPillowの結果と比較し、回転・鏡像の一致を確認しました。
- 長辺1600への縮小、JPEG化、出力のEXIF除去を確認しました。
- EXIFのない正常HEICは撮影日・GPSを補完せず読み込めます。破損HEICは拒否します。
- stored/deflatedの単一写真ZIPを標準のDecompressionStreamで読みました。
  macOSの付帯ファイルを除外し、展開原本のSHA-256一致を確認しました。
  複数写真、不正な親パス、CRC破損は拒否します。ファイルをディスクへ展開しません。

exifr 7.1.3のHEIF iloc処理がbase_offsetを無視するため、probe.mjsに局所補正があります。
配布ライブラリのファイルは変更していません。単一extent、file-offset方式だけを扱い、
他のconstruction_methodや複数extentは未対応としてエラーにします。
EXIF自体がないケースは正常として扱います。

JPEGのquality値は既存と同じ0.86相当ですが、Canvasの縮小・圧縮はPillowの
LANCZOS/optimizeと同一アルゴリズムではありません。識別品質の同等性は未検証です。
画質判定のブラウザ移植もまだ行っていません。

ZIPは通常の単一ディスク・非ZIP64、UTF-8またはASCIIファイル名に限定した実験です。
Python ZipFileとの完全互換を確認したものではありません。CP437名、ZIP64、特殊な
ディレクトリ配置、暗号化などについて本番採用前に扱いを決める必要があります。
展開中の実サイズを15 MiB以内に制限し、最終サイズとCRCを確認します。

実機Android/iOS、実写真、HDR/色域、Live Photo/複数画像、巨大画像のメモリ、
Safari/Firefox、ZIPの全エラー条件、識別結果の同等性、公開環境は未検証です。
この検証だけでHEIC対応全体やCloudflare移行の完了を宣言しません。
