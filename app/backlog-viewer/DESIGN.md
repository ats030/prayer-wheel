# DESIGN.md

## Visual Theme

This app uses a Linear-inspired product UI: dark, precise, dense, and quiet. The interface should feel like an engineering tool for scanning a backlog and deciding what to drop, not a marketing page.

Use a near-black canvas, subtle layered surfaces, fine borders, restrained typography, and one purple accent for primary actions and active state. Keep decorative effects minimal.

Reference source: VoltAgent `awesome-design-md` describes Linear as "Project management for engineers. Ultra-minimal, precise, purple accent" and recommends copying a `DESIGN.md` into the project root for AI-assisted UI work.

## Colors

| Token | Hex | Role |
|---|---:|---|
| `bg` | `#08090c` | App canvas |
| `surface` | `#0d0f14` | Sidebar and panels |
| `surface-raised` | `#12141b` | Containers, expanders, inputs |
| `surface-hover` | `#171923` | Hover state |
| `border` | `#242633` | Default divider and control border |
| `border-strong` | `#343747` | Focus and active borders |
| `text` | `#f4f4f5` | Main text |
| `muted` | `#a1a1aa` | Secondary text |
| `subtle` | `#71717a` | Captions and metadata |
| `accent` | `#7c3aed` | Primary action and active state |
| `accent-soft` | `#a78bfa` | Hover text and links |
| `success` | `#34d399` | Positive status |
| `warning` | `#fbbf24` | Warning status |
| `danger` | `#fb7185` | Destructive action |

## Typography

- Use the system sans stack: Inter if available, otherwise SF Pro, Segoe UI, Helvetica, Arial.
- Body text should be 14-15px and compact.
- Headings should be precise rather than oversized.
- Avoid negative letter spacing and decorative display styles.
- Metadata should be muted and smaller, usually 12-13px.

## Components

- Buttons: 6px radius, compact height, thin border. Primary buttons use purple with white text. Secondary buttons stay dark with neutral borders.
- Inputs and selects: dark raised surface, 6px radius, crisp focus ring using purple.
- Sidebar: persistent dark navigation surface with a fine right border.
- Lists and expanders: dense rows with subtle raised surfaces, 8px radius or less, no nested decorative cards.
- Tags and code-like badges: small purple-tinted chips on dark surfaces.
- Links: use soft purple, with a brighter hover state.

## Layout

- Keep content constrained enough to scan, but use the available width for lists.
- Prefer dense spacing: 8, 12, 16, 24, and 32px.
- Separate regions with borders and whitespace rather than heavy shadows.
- Avoid hero layouts, large decorative cards, gradients, and illustration-led composition.

## Interaction

- Hover states should be subtle surface or border changes.
- Active navigation and primary actions should be immediately visible via purple.
- Disabled states should look intentionally muted, not broken.

## Do

- Build a calm productivity surface.
- Prioritize scan speed for the backlog table; the reader is triaging dozens of rows in one sitting.
- Use one accent color sparingly.
- Keep radius at 6-8px.

## Don't

- Do not use bright multicolor palettes.
- Do not add ornamental gradients, blobs, or large rounded cards.
- Do not create landing-page style sections.
- Do not make text or controls oversized for this workflow.

## Charts (backlog-viewer 固有)

グラフはサーバ側で SVG を組み立てる。チャートライブラリを入れない。依存を1つ足すと
ライセンス確認と更新追従が新しい運用タスクになり、このアプリが可視化しようとしている
問題そのものを増やす。

積み上げ層の色は accent (`#7c3aed`) の**明度違いだけ**で階調を作る。上の
"Do not use bright multicolor palettes" を守るため、色相は 258 に固定し、古いコホートを
暗く、新しいコホートを明るくする。`deferred` (外部待ち) の層だけは意味が違うので
無彩色 `#3f3f46` を使い、purple の階調から外す。

数値は `font-variant-numeric: tabular-nums` で桁を揃える。滞留日数は 14日超を warning、
30日超を danger の色で示す。これが唯一の多色使用で、それ以外に色で意味を運ばない。
