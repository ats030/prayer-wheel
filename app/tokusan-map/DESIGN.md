# Design — Tokusan Map

Tokusan Map の全画面で共有するデザイン規約です。正本は姉妹アプリの
`omatsuri-map/DESIGN.md` で、ここには特産物固有の差分だけを加えます。
画面ごとにテーマを作り直さず、変更が必要な場合はこの文書を先に更新します。

## Genre

modern-minimal。地図と特産物の情報そのものを主役にし、装飾は控えます。

## Macrostructure family

- App pages: Workbench。PCでは検索・一覧パネルと地図を並置し、モバイルでは地図の下に操作パネルを配置します。
- Content pages: Long Document。特産物の詳細と出典を読みやすい一列で表示します。

## Theme

色の役割は omatsuri-map と同じです（生成りの面、濃紺の文字、朱色は選択状態に限定）。
値は `frontend/tokens.css` の `--color-*` で定義し、純白・純黒は使いません。

### カテゴリ色

品目（カテゴリ）ごとに1色を割り当て、`--color-cat-*` としてマーカー・凡例・バッジで共用します。

- `--color-cat-sa` 酒・醸造
- `--color-cat-te` 茶・飲料
- `--color-cat-ui` 魚介
- `--color-cat-sa2` 農産
- `--color-cat-am` 砂糖・和菓子
- `--color-cat-ko` 穀物・調味料
- `--color-cat-ry` 料理・惣菜
- `--color-cat-ta` 陶磁器
- `--color-cat-or` 織物
- `--color-cat-ri` 漆器
- `--color-cat-kg` その他工芸（伝統的工芸品のうち陶磁器・織物・漆器以外）

未分類の品目は掲載しません（`data/curation.json` で必ず分類します）。

## Typography / Spacing / Motion / Microinteractions stance

omatsuri-map と同じです。ゴシック体、4px基準の `--space-*`、`--ease-out` による短い遷移を使います。

## Component voice

- Map marker: 品目のカテゴリ色で表し、選択時は朱色の輪郭で表します。`map-legend` の凡例で意味を示します。
- 一覧と地図のツールチップは、都道府県単位の品目にその旨を明示します。

## Per-page allowances

アプリ画面には装飾用イラストや背景エフェクトを追加しません。特産物の写真、地図、実データを視覚要素にします。

### 詳細パネル

上から次の順で表示します。順序は固定です。

1. 名称と品目バッジ（タイトル直下）
2. 基本情報: 産地・都道府県（品目は1のバッジで示し、重複させません）
3. 写真（Wikimedia Commons。ライセンスを確認できない画像は表示しません）
4. **◯◯について** — その特産物が何かの概要。
5. **歴史** — 起源と変遷。
6. **産地・製法** — 産地の条件、原料、作り方。
7. **購入・観光** — 買える場所、関連する施設や行事。
8. 出典（Wikipedia と Wikidata へのリンク）

4〜7の節は Wikipedia 本文から LLM が要約します。内容のない節は見出しごと表示しません。

産地の行には必ず注記を付けます。

- 通常の品目: 「推定」。産地と座標は目安です。
- 都道府県単位の品目（`prefecture_level`）: 「都道府県単位」。地図上は都道府県庁の位置に表示します。

信頼度の数値、LLM が抽出した根拠文、宿泊施設などの周辺情報は表示しません。

## What pages MUST share

- 藍色と朱色の役割
- 表示書体と本文書体
- フォーカス、ボタン、入力欄、一覧項目の形
- 4px基準の余白と短い状態遷移

## What pages MAY differ on

- 地図の有無
- 一覧の列数
- 詳細表示の密度
