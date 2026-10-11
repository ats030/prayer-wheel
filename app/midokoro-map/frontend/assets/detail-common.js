// Detail-panel behaviour shared by every category view.
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]);
}

export function sourceLink(href, label) {
  return /^https?:\/\//.test(href || '') ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}<span aria-hidden="true">↗</span></a>` : '';
}

export function reducedMotion() {
  return matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function flyToItem(map, latlng) {
  const zoom = Math.max(map.getZoom(), 8);
  if (reducedMotion()) map.setView(latlng, zoom, {animate:false});
  else map.flyTo(latlng, zoom, {duration:.55});
}

export function fitItem(map, bounds, options = {}) {
  map.fitBounds(bounds, {...options, animate:!reducedMotion()});
}

// Focus the title without scrolling, then bring the panel into view only when the
// title is not fully visible (on phones the panel sits above or below the list).
export function revealDetail(map, panel, title) {
  requestAnimationFrame(() => {
    map.invalidateSize();
    title?.focus({preventScroll:true});
    const rect = (title || panel).getBoundingClientRect();
    if (rect.top < 0 || rect.bottom > innerHeight) panel.scrollIntoView({block:'start', behavior:reducedMotion() ? 'auto' : 'smooth'});
  });
}

export function focusWithin(panel) {
  const active = panel.getRootNode().activeElement;
  return Boolean(active && panel.contains(active));
}

// Candidates are tried in order; removed or hidden ones are skipped so focus never falls to body.
export function focusFirst(...candidates) {
  for (const target of candidates) {
    if (!target?.isConnected || target.closest('[hidden]')) continue;
    target.focus();
    if (target.getRootNode().activeElement === target) return target;
  }
  return null;
}
