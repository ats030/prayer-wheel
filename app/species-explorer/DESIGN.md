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
- Candidate cards expose visible traits, uncertainty, and source-search links.
- Images are processed in memory, EXIF metadata is stripped, and nothing is saved.
- Settings are reachable from the header and use a dedicated page with a clear
  return path. API keys are write-only in the UI; configured state and allowed model choices remain visible.

## Responsive behavior

- One column below 760px; preview and results share two columns above it.
- Content never requires horizontal scrolling.
- Focus indicators remain visible and motion respects reduced-motion settings.
