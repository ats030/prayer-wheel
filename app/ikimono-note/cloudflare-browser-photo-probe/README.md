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
画質判定の隔離実験は以下に記載しています。本番移植は未実施です。

ZIPは通常の単一ディスク・非ZIP64、UTF-8またはASCIIファイル名に限定した実験です。
Python ZipFileとの完全互換を確認したものではありません。CP437名、ZIP64、特殊な
ディレクトリ配置、暗号化などについて本番採用前に扱いを決める必要があります。
展開中の実サイズを15 MiB以内に制限し、最終サイズとCRCを確認します。

実機Android/iOS、実写真、HDR/色域、Live Photo/複数画像、巨大画像のメモリ、
Safari/Firefox、ZIPの全エラー条件、識別結果の同等性、公開環境は未検証です。
この検証だけでHEIC対応全体やCloudflare移行の完了を宣言しません。

## 画質判定の比較

同じローカルサーバーを使い、追加の合成画像を生成して検証します。

```sh
/home/ats030/.venv/bin/python generate_quality.py
/home/ats030/.nvm/versions/node/v24.19.0/bin/node check_quality.mjs
```

既存の `image_quality.py` を正解側として、サイズ199/200・299/300、明るさ14/15・
24/25と丸め境界14.95/24.95、コントラスト9/10/11、段階的なぼかしと固定seedのRGBノイズを含む54画像を
比較しました。これは画質判定の互換性検証であり、識別AIの精度評価ではありません。

Canvasの高品質縮小では、800x600のぼかし画像で既存のsharpness 50.6に対し41.7と
なり、ブラウザ側だけがblurry警告を出しました。54画像の最大sharpness差は1285.7です。
既存閾値をそのままCanvasの指標へ適用する方法は採用しません。

`resample.mjs` はPillow 12.2.0のbicubic係数・22bit固定小数点丸め・水平/垂直の
各段階での8bitクリップに合わせた実装です。参照元と利用条件は
`../docs/tool-license-browser-resample-probe.yaml`、著作権と許諾文は
`PILLOW-LICENSE.txt` に保存しています。追加のランタイム依存はありません。

`round.mjs` はbinary64の値を整数比として扱い、Pythonの小数1桁の丸めに合わせます。
JSで値を10倍してから丸めると14.95が15.0になり、Pythonの14.9と暗さ判定が
変わるためです。14.95/24.95と半偶数丸めのassertを追加しています。

この縮小とRGB→L変換・互換丸めを使うと、54画像のsharpness差は0、明るさ・コントラスト・
最終判定も一致しました。比較結果は生成物 `fixtures/quality-comparison.json` に
保存します。数値差が0.1を超えるか判定が不一致の場合、全比較を保存して終了コード2を返します。
補正前のCanvas結果も記録するため、差の再現が可能です。

入力は不透明なRGB PNGの合成画像に限ります。JPEG/HEICのデコード差、透過画像、
色管理、実写真、巨大画像の資源上限、
実機・別ブラウザは未検証です。写真送信用のLANCZOS縮小/JPEG圧縮と識別結果の
比較は別の未完了項目です。このコードは本番へ組み込んでいません。
