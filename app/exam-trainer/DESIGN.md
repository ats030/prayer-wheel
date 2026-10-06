# Design — exam-trainer

User-approved direction: a dark interface centred on finding a検定, trying ten
questions, and saving its PDF. The existing Linear-derived colours and system
fonts in `static/linear.css` are the source of tokens. No new font or dependency.

## Genre and structure

- Modern minimal, functional and restrained. No ornamental images or motion.
- Catalog: short introduction followed by five compact course rows. Trial is
  the primary action; PDFs and an introduction are secondary. Use real counts.
- Product introduction: title, trial action, scope, PDF invitation and details.
- Trial: one question, choices, feedback, then a result with PDF and explanation
  actions. Keep sales information out of the unanswered question area.
- Materials: two learning PDFs first; five production resources in a native
  disclosure. Collapsing information never changes access permissions.
- Sample: readable question/answer articles with reference links.
- Learning: mobile-first question workbench, separate scope/queue controls,
  persistent request feedback, readable answer/explanation and next action.
- Weakness: sectioned progress rows with labelled accuracy and a per-scope study link.
- Administration: desktop-first list/filter workbench and sectioned settings,
  accessible native dialogs, explicit pending/error states; usable on mobile.

## Locked theme and typography

Use `--canvas`, `--surface-1`, `--surface-2`, `--hairline`, `--hairline-strong`,
`--ink`, `--ink-muted`, `--ink-subtle`, `--primary`, `--primary-hover`,
`--warning`, `--success`, `--danger`, `--font` and `--mono` from linear.css.
Display/body are the existing system sans font; headings are upright, weight
600. Title scale: clamp(28px, 5vw, 42px). Body: 16px, line height 1.6–1.7.
No gradients or shadows. Accent belongs on the primary action and current state.

## Spacing, controls and motion

Named spacing tokens follow 4px multiples: 4, 8, 12, 16, 24, 32, 48px.
Existing radius tokens remain. Links/buttons in the learner flow have a minimum
44px touch target and do not wrap their labels. Focus is visible; use native
links, buttons, details and progress. No entry animations or celebratory toasts.
Requests show a pending state, errors allow retry, unavailable/stale PDFs show
their status without offering broken downloads.

## Shared navigation and honest status

All public views share 教材を探す and 学習を続ける. Learning additionally has 弱点.
Product views have a local navigation with a current-page indicator. `/` and
`/products` show the catalog; `/study` is learning. Existing root links containing
exam_id/node continue to open learning.
Unreviewed, sale preparation and revision-pending states remain visible.
Visual polish does not imply human proofreading or full exam coverage.

## Responsive verification

Use 320, 375, 414, 768 and desktop widths. Course rows stack on mobile, PDF
columns become one, headings wrap, actions keep single-line labels. Fix layout
overflow at its source; do not hide inaccessible content to make a check pass.

## Per-page allowances

Page structure varies by purpose; theme, type, control voice and section rhythm
are shared. Administrative screens share the system and retain existing operations.
No change to content, learner history, scheduling, auth or file gates. Native
dialogs trap focus, close with Escape and restore focus to the opener.
