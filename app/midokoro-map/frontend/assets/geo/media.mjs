// HTML for a natural monument's photo and AI section summaries in the geo detail panel.
// Pure functions so scripts/test-geo-media.mjs can check them without a browser.

// Response slots of /api/geo/wiki/content in display order.
export const SECTIONS = [['history', '成り立ち'], ['remains', '特徴・見どころ'], ['access', 'アクセス'], ['highlights', '指定・保護']];

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[char]);
}

export function httpUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}

// photo: {url, license, licenseUrl, creator, sourceUrl} with plain-text fields, or null.
// Returns the inner HTML of #detail-photo.
export function photoHtml(photo, name) {
  throw new Error('not implemented');
}

// content: /api/geo/wiki/content response, or null.
// Returns the HTML for the summarized sections, or '' when no slot has a summary.
export function sectionsHtml(content) {
  throw new Error('not implemented');
}

// True when the response carries at least one non-empty summary; the view caches only these.
export function hasSummary(content) {
  throw new Error('not implemented');
}
