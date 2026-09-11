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
- Map marker: 選択時のみ朱色へ変化させます。

## Per-page allowances

アプリ画面には装飾用イラストや背景エフェクトを追加しません。祭りの写真、地図、実データが視覚要素です。

## What pages MUST share

- 藍色と朱色の役割
- 表示書体と本文書体
- フォーカス、ボタン、入力欄、一覧項目の形
- 4px基準の余白と短い状態遷移

## What pages MAY differ on

- 地図の有無
- 一覧の列数
- 詳細表示の密度
