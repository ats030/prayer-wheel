// HTML for a natural monument's photo and AI section summaries in the geo detail panel.
// Pure functions so scripts/test-geo-media.mjs can check them without a browser; package.json here marks them as ES modules for Node.

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
  const url = httpUrl(photo?.url);
  if (!url) {
    return '<p class="detail-image-status">表示できる画像が登録されていません。</p>';
  }
  if (!photo.license) {
    return '<p class="detail-image-status">画像のライセンス情報を確認できないため、表示していません。</p>';
  }
  const parts = [];
  if (photo.creator) {
    parts.push(esc(photo.creator));
  }
  const licenseUrl = httpUrl(photo.licenseUrl);
  if (licenseUrl) {
    parts.push('<a href="' + esc(licenseUrl) + '" target="_blank" rel="noopener noreferrer">' + esc(photo.license) + '</a>');
  } else {
    parts.push(esc(photo.license));
  }
  const sourceUrl = httpUrl(photo.sourceUrl);
  if (sourceUrl) {
    parts.push('<a href="' + esc(sourceUrl) + '" target="_blank" rel="noopener noreferrer">出典</a>');
  }
  return '<figure class="detail-photo"><img class="detail-image" src="' + esc(url) + '" alt="' + esc(name) + 'の写真" loading="lazy"><figcaption>' + parts.join(' · ') + '</figcaption></figure>';
}

// content: /api/geo/wiki/content response, or null.
// Returns the HTML for the summarized sections, or '' when no slot has a summary.
export function sectionsHtml(content) {
  if (!hasSummary(content)) {
    return '';
  }
  let html = '';
  for (const [key, label] of SECTIONS) {
    const summary = (content[key]?.summary ?? '').trim();
    if (summary) {
      html += '<section class="detail-section"><h3>' + label + '</h3><p class="detail-summary">' + esc(summary) + '</p></section>';
    }
  }
  const sourceUrl = httpUrl(content.source_url);
  if (sourceUrl) {
    html += '<p class="detail-source">要約はAIが<a href="' + esc(sourceUrl) + '" target="_blank" rel="noopener noreferrer">Wikipedia</a>の記事（CC BY-SA 4.0）から作成しました。</p>';
  } else {
    html += '<p class="detail-source">要約はAIがWikipediaの記事（CC BY-SA 4.0）から作成しました。</p>';
  }
  return html;
}

// True when the response carries at least one non-empty summary; the view caches only these.
export function hasSummary(content) {
  if (!content) return false;
  return SECTIONS.some(([key]) => (content[key]?.summary ?? '').trim() !== '');
}
