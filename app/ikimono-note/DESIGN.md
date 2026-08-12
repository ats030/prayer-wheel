# 生きものノート (ikimono-note) Design Guide

## Direction

生きものノート (internally ikimono-note) is a phone-first field tool for all ages. It keeps the stack's
compact layout discipline but reads as daylight fieldwork rather than a console:
a light canvas, one green accent, and the photograph and identification
candidates as the visual focus. It must feel careful rather than authoritative:
model output is always presented as a candidate that the user should compare
with the subject.

## Audience

- No age restriction. Copy targets a reader around upper primary school:
  everyday words instead of jargon ("似ている生きもの" not "識別候補",
  "決め手が足りない理由" not "確証がない理由"), no furigana, no baby talk.
- One word per concept, across every screen. The capture and history screens say
  調べる (not 識別/判定), 記録 (not 履歴), 誤差 (not 精度), 図鑑データ (not
  図鑑データベース), and Ollama — the actual name of the thing, not ローカルLLM or
  ローカルAI. A vague label hides where the photo goes; "Ollama" says it, and the
  status line and the settings radio then agree with each other and with reality.
  Photo EXIF is 写真の情報, never 記録, because 記録 already means the
  on-device history. Settings and the legal pages may keep 識別 for precision,
  but when they quote a control they quote its actual label.
- The same vocabulary binds server error messages. A `detail=` string that says
  画像 or 計算資源 while the screen says 写真 and 使うAI makes one thing look like
  two. Tests assert the banned words never appear in `detail=` / `VisionError()`.
- Split the audience in failures. The user gets what to do next ("少し待ってから
  もう一度お試しください"); the operator gets the cause, in the journal — env var
  names, token counts, `finishReason`. Putting the operator's half on screen
  hands a public visitor a variable they cannot set; putting the user's half
  only on screen leaves the operator guessing. Both halves, separate channels.
- Terms and privacy state the all-ages position explicitly and place the
  API-key contract and the cost with the account holder, not the child.
- Nothing about the safety position softens for the younger reader; it gets
  louder. Plain-language warnings replace clinical ones.

## Visual system

- Near-white canvas with a faint green cast, white panels, hairline borders,
  and one green accent. `prefers-color-scheme: dark` swaps the same token names
  to a dark-green-tinted set; no page defines a color only inside the dark
  block, and `color-scheme: light dark` is declared on every page.
- The reader can override the device setting. `theme.js` runs synchronously in
  `<head>` — before any style — and stamps `data-theme="light"|"dark"` on the
  root from `localStorage`, so a chosen theme never flashes the other one. Dark
  tokens are therefore declared twice per page: inside
  `@media(prefers-color-scheme:dark){:root:not([data-theme="light"])}` and again
  in `:root[data-theme="dark"]`, so an explicit choice wins in both directions.
  The toggle cycles 自動 → ライト → ダーク; 自動 clears the stored key and hands
  control back to the device. It also swaps the `theme-color` meta, because the
  media-based ones follow the OS and would otherwise contradict the choice.
- The toggle sits with the other header actions on every page and keeps its
  44px target. Below 390px only its icon remains — the label is the first thing
  to fold, never the button.
- Filled controls use `--on-accent` so the accent keeps contrast in both themes.
- System sans typography, 4px spacing grid, 8px controls, and 12px cards.
- No decorative gradients, oversized headings, or unrelated imagery. The one
  ornament is the ⚠ mark on the safety card.
- Confidence is expressed with plain text and a restrained meter, never a green
  "correct" state — the accent is the app's own color, not a verdict.

## Interaction

識別候補は schema-first で観察点・類似種との識別点・矛盾を分離する。学名の完全一致だけを表示の必須条件とし、写真上の証拠が不足する候補は「確証なし」と不足理由を表示する。自己申告スコアは証拠ありで60%、証拠不足で30%、矛盾ありで20%を上限とする。画面上の観察点はAI抽出で未検証と明示する。

- The main screen uses a Workbench flow: capture, preview, then full-width results. Camera and library inputs are the primary actions and have 44px touch targets.
- Optional capture context and advanced identification controls stay in closed disclosures until requested. After an image is selected, the capture target compresses so the preview and identify action become the visual priority.
- Safety guidance is one flat warning region rather than nested cards; related products form one non-sticky shelf after all candidates instead of repeating per candidate; the product query always follows the first candidate. Rotating through candidates made the advert drift onto the second or third guess, and the reader could not tell which candidate the products belonged to.
- The safety region opens with a lead sentence addressed to the whole audience, then splits into three equal questions the app refuses to answer or cannot answer alone: 食べられるか, さわってよいか, 持ち帰ってよいか. Touch safety is stated because rash-causing plants and stinging animals are not separable from a photograph.
- The chosen image is previewed before identification.
- Identification shows an expected wait and disables duplicate submission.
- Empty, loading, result, and error states do not shift the main capture controls.
- Strict mode automatically checks VLM scientific names against iNaturalist and hides non-exact matches.
- VLM candidates label photo observations as unverified AI extraction, cap the displayed score, and separate observations from discriminating features.
- Specialist plant candidates retain their Pl@ntNet source, and exact VLM agreement is labeled as two independent paths.
- If every candidate is rejected, the result asks for additional identifying photos instead of filling the gap with a guess.
- Whatever the result still leaves unsettled — もっと確かめたいこと, 決め手が足りない理由, or no candidate at all — is followed in the same block by the two ways to answer it: カメラで撮って足す and 写真を選んで足す. Advice about what to photograph is only advice until the camera is one press away, and the reader is standing in front of the subject while they read it. The block is shown whenever anything is left to check, not only when a candidate lacks decisive evidence.
- Added photos join the current selection instead of replacing it, up to the same three. The first frame is usually the whole organism; replacing it with the close-up the guide asked for would restart identification from less than it had. Identification is still one explicit press of 名前を調べる — adding a photo scrolls there and says so rather than spending a request on its own.
- Affiliate product-search templates expand the verified candidate name plus identification category into {query}. When configured, Amazon Creators API may replace that fallback with up to four returned product cards containing an image, title, and detail-page URL; each link is labeled as advertising and never influences generation or ranking.
- When affiliate advertising is enabled, it remains visible; only aggregate impressions and clicks are stored.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Before stripping EXIF, the local server may propose its capture date and GPS rounded to four decimals. The disclosure opens so users can review or edit these values before they are sent as identification context.
- Identification history is owned by the browser: at most 50 records, result fields, reviewed context, rounded coordinates, and a maximum-320px JPEG thumbnail are stored in IndexedDB. There is no history API or server-side history file.
- The capture screen writes history; `/history` is the only screen that reads it. The capture screen keeps no second, hidden copy of the list — a panel nobody can open is a place for failures to go unseen, so a failed write surfaces in the same status line the identification uses.
- Location history never loads a third-party map automatically, on any screen. `/history` shows the privacy note and a button; only the press loads Leaflet and requests OpenStreetMap tiles, with visible attribution and an explicit warning that the rounded coordinate leaves the browser. With no located record the button is disabled and says so.
- Leaflet is vendored under `static/vendor/` rather than pulled from a CDN, so opening the history page cannot hand a visitor's address to a third party the privacy policy never named. Its BSD-2-Clause license text ships alongside it.
- No page carries an inline `<style>`, an inline `<script>`, a `style` attribute, or an `on*` handler. Every page's CSS and JS lives in `/assets/<page>.css` and `/assets/<page>.js`, which is what lets the CSP drop `'unsafe-inline'` — the app hands visitors' API keys to the browser, so a stray injection must not be able to run. Values computed at runtime (the confidence meter's width) go through the CSSOM, never a `style` attribute string. Adding an inline block anywhere silently breaks that page under CSP; tests assert the absence.
- Geolocation is requested only after an explicit button press, kept in browser memory for the current page, reduced to an accuracy label in the result, and never added to identification requests or storage.
- The app never grants collection or edibility. It lists unresolved owner, protected-area, ordinance, and protected-species checks and links to authoritative Japanese guidance.
- Optional specialist services remain hidden until configured and require an explicit per-request photo-sharing choice.
- Settings are reachable from the header and use a dedicated page with a clear
  return path. API keys are write-only in the UI; configured state and allowed model choices remain visible.
- Public mode keeps each visitor's provider and model choice in localStorage,
  but API keys only in sessionStorage. Keys are submitted with an identification
  request and are never written to server settings or browser history.
- Public mode makes operator settings read-only, rejects arbitrary Ollama URLs,
  and disables operator-funded local inference unless explicitly enabled.
- External-provider copy states where photographs are sent; Gemini also distinguishes unpaid data-improvement handling from paid-service handling.
- Gemini identification performs a bounded observe, compare-lookalikes, reject-contradictions pass before schema-constrained output; high thinking is preferred for accuracy, while the independent taxonomy gate still treats the photo match as unverified.
- Animal candidates include a sex estimate only when at least one directly visible, species-specific sexual-dimorphism feature is supplied. Otherwise the UI says undetermined; plants are out of scope. The estimate remains explicitly model-derived and requires comparison with a taxon-appropriate external reference.
- Animal reference links are routed by iNaturalist's verified iconic taxon: ADW for mammals, Cornell for birds, FishBase for fishes, AmphibiaWeb for amphibians, Reptile Database for reptiles, and GBIF otherwise. These sites are linked for human review only; their content is not scraped or treated as automatic proof.

## Responsive behavior

- One column below 760px; capture and preview share the Workbench columns above it, with results spanning both columns.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
