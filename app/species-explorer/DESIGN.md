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

- The main screen uses a Workbench flow: capture, preview, then full-width results. Camera and library inputs are the primary actions and have 44px touch targets.
- Optional capture context and advanced identification controls stay in closed disclosures until requested. After an image is selected, the capture target compresses so the preview and identify action become the visual priority.
- Safety guidance is one flat warning region rather than nested cards; related products form one shelf after all candidates instead of repeating per candidate.
- The chosen image is previewed before identification.
- Identification shows an expected wait and disables duplicate submission.
- Empty, loading, result, and error states do not shift the main capture controls.
- Strict mode automatically checks VLM scientific names against iNaturalist and hides non-exact matches.
- Taxonomy-only candidates state that the photo match is unverified; generated common names, traits, and probability are not presented as facts.
- Specialist plant candidates retain their Pl@ntNet source, and exact VLM agreement is labeled as two independent paths.
- If every candidate is rejected, the result asks for additional identifying photos instead of filling the gap with a guess.
- Affiliate product-search templates expand the verified candidate name plus identification category into {query}. When configured, Amazon Creators API may replace that fallback with up to four returned product cards containing an image, title, and detail-page URL; each link is labeled as advertising and never influences generation or ranking.
- Users can hide the ad locally and restore it from Settings; only aggregate impressions and clicks are stored.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Geolocation is requested only after an explicit button press, kept in browser memory for the current page, reduced to an accuracy label in the result, and never added to identification requests or storage.
- The app never grants collection or edibility. It lists unresolved owner, protected-area, ordinance, and protected-species checks and links to authoritative Japanese guidance.
- Optional specialist services remain hidden until configured and require an explicit per-request photo-sharing choice.
- Settings are reachable from the header and use a dedicated page with a clear
  return path. API keys are write-only in the UI; configured state and allowed model choices remain visible.
- External-provider copy states where photographs are sent; Gemini also distinguishes unpaid data-improvement handling from paid-service handling.
- Gemini identification performs a bounded observe, compare-lookalikes, reject-contradictions pass before schema-constrained output; high thinking is preferred for accuracy, while the independent taxonomy gate still treats the photo match as unverified.

## Responsive behavior

- One column below 760px; capture and preview share the Workbench columns above it, with results spanning both columns.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
