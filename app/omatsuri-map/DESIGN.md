# Design — Omatsuri Map

Omatsuri Map の全画面で共有するデザイン規約です。画面ごとにテーマを作り直さず、必要な場合はこの文書を先に更新します。

## Genre

modern-minimal。地図と祭り情報そのものを主役にし、装飾は控えます。

## Macrostructure family

- App pages: Workbench。PCでは検索・一覧パネルと地図を並置し、モバイルでは地図の下に操作パネルを配置します。
- Content pages: Long Document。祭りの詳細や出典を読みやすい一列で表示します。

## Theme

- `--color-paper`: 温かみのある生成り
- `--color-paper-2`: 薄い藍鼠
- `--color-ink`: 墨に近い濃紺
- `--color-ink-2`: 藍鼠
- `--color-rule`: 淡い藍鼠
- `--color-accent`: 朱色（選択・開催状態に限定）
- `--color-focus`: 明るい青

純白・純黒は使いません。色はCSSカスタムプロパティを通して使用します。

### カテゴリ色

祭りの種別（カテゴリ）には、各カテゴリに1色を割り当てます。`--cat-*` という名前
のトークンとして定義し、マーカー・凡例・バッジで共用します。

- `--cat-mt: #a2543f` 山車・屋台
- `--cat-hb: #4a5a8a` 花火
- `--cat-ma: #3a7d76` 演舞・盆踊り
- `--cat-kw: #557a46` 行列・渡御
- `--cat-jr: #9a7b2d` 神事・祭礼
- `--cat-hn: #b85c2a` 灯籠・火祭り
- `--cat-si: #6b7f3f` 博覧会・市
- `--cat-js: #7a6a52` 行事
- `--cat-kt: #68737d` その他 / 未分類

## Typography

- Display: `system-ui, -apple-system, "Yu Gothic", sans-serif`, weight 700, normal
- Body: `system-ui, -apple-system, "Yu Gothic", sans-serif`, weight 400
- Numeric: body font with tabular figures

祭り名、操作ラベル、本文のすべてにゴシック体を使います。

## Spacing

4pxを基準とする名前付きスケールを使います。主要な値は `--space-*` として各HTMLのトークンブロックに定義します。

## Motion

- `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`
- 選択、色、1px以内の移動だけを短時間で遷移させます。
- `prefers-reduced-motion` では遷移を無効にします。

## Microinteractions stance

- フォーカスリングは即時表示します。
- ホバーだけに重要な情報を置きません。
- 成功トーストやスクロール連動アニメーションは使いません。
- クリック可能な文言は折り返しません。

## Component voice

- Primary action: 朱色の塗り。選択や現在地など、画面内で一つの意味に限定します。
- Secondary action: 生成りの面に藍色の細い境界線。
- Cards: 外側に余分なカードを重ねず、一覧の罫線と面の差で区切ります。
- Map marker: 先頭カテゴリに応じて種別カラー(各カテゴリに1色を割り当てる)で表します。選択時は朱色の輪郭で表します。`map-legend` 凡例で意味を示します。
- 姉妹アプリ(onsen/shiseki)と同一の色意味を持ちます。色は CSS カスタムプロパティで定義します。

## Per-page allowances

アプリ画面には装飾用イラストや背景エフェクトを追加しません。祭りの写真、地図、実データが視覚要素です。

### 詳細パネルの節

Wikipedia 由来の情報を5つの節に整理して表示します。節は固定語彙で、
LLM が文章を要約・構造化しますが、節の枠組みそのものは固定です。

- **歴史・由来** — 起源、開創・中興の経緯、時代を通じた変遷。
- **見どころ** — 高潮となる行事、主役となる山車・屋台・武者行列、特別な演出など「祭りの核」。
- **お祭りの流れ** — 当日のスケジュールを時系列で。早朝から終礼まで、行事名と時間の対応。
- **アクセス** — 最寄り駅・路線、駅からの導線、駐車場・アクセス経路。
- **周辺観光** — その地域・神社・寺社近隣の観光スポット・施設。

各節は LLM が `summary` 一文と `items`(label + value 行)を返す構造化形式で表示します。
`items` が無ければ `summary` のみ、それも無ければ Wikipedia 本文の見出し単位のブロックを表示します。
文化財区分はバッジとして詳細パネルの上部(タイトル直下)に表示します。

## What pages MUST share

- 藍色と朱色の役割
- 表示書体と本文書体
- フォーカス、ボタン、入力欄、一覧項目の形
- 4px基準の余白と短い状態遷移

## What pages MAY differ on

- 地図の有無
- 一覧の列数
- 詳細表示の密度
