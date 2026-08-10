# Species Explorer Design Guide

## Direction

Species Explorer is a phone-first field tool for all ages. It keeps the stack's
compact layout discipline but reads as daylight fieldwork rather than a console:
a light canvas, one green accent, and the photograph and identification
candidates as the visual focus. It must feel careful rather than authoritative:
model output is always presented as a candidate that the user should compare
with the subject.

## Audience

- No age restriction. Copy targets a reader around upper primary school:
  everyday words instead of jargon ("似ている生きもの" not "識別候補",
  "決め手が足りない理由" not "確証がない理由"), no furigana, no baby talk.
- Terms and privacy state the all-ages position explicitly and place the
  API-key contract and the cost with the account holder, not the child.
- Nothing about the safety position softens for the younger reader; it gets
  louder. Plain-language warnings replace clinical ones.

## Visual system

- Near-white canvas with a faint green cast, white panels, hairline borders,
  and one green accent. `prefers-color-scheme: dark` swaps the same token names
  to a dark-green-tinted set; no page defines a color only inside the dark
  block, and `color-scheme: light dark` is declared on every page.
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
- Safety guidance is one flat warning region rather than nested cards; related products form one non-sticky shelf after all candidates instead of repeating per candidate; repeated identifications rotate the candidate used for the product query.
- The safety region opens with a lead sentence addressed to the whole audience, then splits into three equal questions the app refuses to answer or cannot answer alone: 食べられるか, さわってよいか, 持ち帰ってよいか. Touch safety is stated because rash-causing plants and stinging animals are not separable from a photograph.
- The chosen image is previewed before identification.
- Identification shows an expected wait and disables duplicate submission.
- Empty, loading, result, and error states do not shift the main capture controls.
- Strict mode automatically checks VLM scientific names against iNaturalist and hides non-exact matches.
- VLM candidates label photo observations as unverified AI extraction, cap the displayed score, and separate observations from discriminating features.
- Specialist plant candidates retain their Pl@ntNet source, and exact VLM agreement is labeled as two independent paths.
- If every candidate is rejected, the result asks for additional identifying photos instead of filling the gap with a guess.
- Affiliate product-search templates expand the verified candidate name plus identification category into {query}. When configured, Amazon Creators API may replace that fallback with up to four returned product cards containing an image, title, and detail-page URL; each link is labeled as advertising and never influences generation or ranking.
- When affiliate advertising is enabled, it remains visible; only aggregate impressions and clicks are stored.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Before stripping EXIF, the local server may propose its capture date and GPS rounded to four decimals. The disclosure opens so users can review or edit these values before they are sent as identification context.
- Identification history is owned by the browser: at most 50 records, result fields, reviewed context, rounded coordinates, and a maximum-320px JPEG thumbnail are stored in IndexedDB. There is no history API or server-side history file.
- Location history never loads a third-party map automatically. A per-record action loads an OpenStreetMap embed with visible attribution and an explicit warning that the rounded coordinate leaves the browser.
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
