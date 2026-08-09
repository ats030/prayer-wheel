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

- Camera and library inputs are the primary actions and have 44px touch targets.
- The chosen image is previewed before identification.
- Identification shows an expected wait and disables duplicate submission.
- Empty, loading, result, and error states do not shift the main capture controls.
- Strict mode automatically checks VLM scientific names against iNaturalist and hides non-exact matches.
- Taxonomy-only candidates state that the photo match is unverified; generated common names, traits, and probability are not presented as facts.
- Specialist plant candidates retain their Pl@ntNet source, and exact VLM agreement is labeled as two independent paths.
- If every candidate is rejected, the result asks for additional identifying photos instead of filling the gap with a guess.
- Affiliate search-link templates expand only the verified candidate name into {query}. When configured, Amazon Creators API may replace that fallback with its returned product title and detail-page URL; each link is labeled as advertising and never influences generation or ranking.
- Users can hide the ad locally and restore it from Settings; only aggregate impressions and clicks are stored.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Optional specialist services remain hidden until configured and require an explicit per-request photo-sharing choice.
- Settings are reachable from the header and use a dedicated page with a clear
  return path. API keys are write-only in the UI; configured state and allowed model choices remain visible.
- External-provider copy states where photographs are sent; Gemini also distinguishes unpaid data-improvement handling from paid-service handling.

## Responsive behavior

- One column below 760px; preview and results share two columns above it.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
