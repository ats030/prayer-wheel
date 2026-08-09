# Species Explorer Design Guide

## Direction

Species Explorer is a phone-first field tool. It follows the stack's compact,
Linear-inspired dark UI while using the photograph and identification candidates
as the visual focus. It must feel careful rather than authoritative: model output
is always presented as a candidate that the user should compare with the subject.

## Visual system

- Near-black canvas, charcoal panels, hairline borders, and one lavender accent.
- System sans typography, 4px spacing grid, 8px controls, and 12px cards.
- No decorative gradients, oversized headings, or unrelated imagery.
- Confidence is expressed with plain text and a restrained meter, never a green
  "correct" state.

## Interaction

識別候補は schema-first で観察点・類似種との識別点・矛盾を分離する。通常のVLM候補は、観察点2件以上、識別点1件以上、矛盾なし、学名の完全一致をすべて満たす場合だけ表示する。モデルの自己申告スコアは60%を上限とし、条件不足では候補なしへフォールバックする。画面上の観察点はAI抽出で未検証と明示する。

- The main screen uses a Workbench flow: capture, preview, then full-width results. Camera and library inputs are the primary actions and have 44px touch targets.
- Optional capture context and advanced identification controls stay in closed disclosures until requested. After an image is selected, the capture target compresses so the preview and identify action become the visual priority.
- Safety guidance is one flat warning region rather than nested cards; related products form one non-sticky shelf after all candidates instead of repeating per candidate; repeated identifications rotate the candidate used for the product query.
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
- External-provider copy states where photographs are sent; Gemini also distinguishes unpaid data-improvement handling from paid-service handling.
- Gemini identification performs a bounded observe, compare-lookalikes, reject-contradictions pass before schema-constrained output; high thinking is preferred for accuracy, while the independent taxonomy gate still treats the photo match as unverified.
- Animal candidates include a sex estimate only when at least one directly visible, species-specific sexual-dimorphism feature is supplied. Otherwise the UI says undetermined; plants are out of scope. The estimate remains explicitly model-derived and requires comparison with a taxon-appropriate external reference.
- Animal reference links are routed by iNaturalist's verified iconic taxon: ADW for mammals, Cornell for birds, FishBase for fishes, AmphibiaWeb for amphibians, Reptile Database for reptiles, and GBIF otherwise. These sites are linked for human review only; their content is not scraped or treated as automatic proof.

## Responsive behavior

- One column below 760px; capture and preview share the Workbench columns above it, with results spanning both columns.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
