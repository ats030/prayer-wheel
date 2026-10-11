// Detail-panel behaviour shared by every category view.
export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]);
}

export function sourceLink(href, label) {
  const url = safeUrl(href);
  return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}<span aria-hidden="true">↗</span></a>` : '';
}

export function safeUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}

export function plainText(value) {
  const document = new DOMParser().parseFromString(String(value || ''), 'text/html');
  return document.body.textContent.trim();
}

export function commonsFilePage(value) {
  try {
    const url = new URL(value);
    if (!['upload.wikimedia.org', 'thumb.wikimedia.org'].includes(url.hostname)) return '';
    const parts = url.pathname.split('/').filter(Boolean), thumbIndex = parts.indexOf('thumb');
    const fileName = decodeURIComponent(thumbIndex >= 0 ? parts[parts.length - 2] : parts[parts.length - 1]);
    return fileName ? `https://commons.wikimedia.org/wiki/File:${encodeURIComponent(fileName)}` : '';
  } catch { return ''; }
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

export function closeDetailPanel(panel, {key, origin, cardSelector, restoreFocus = true}) {
  const hadFocus = focusWithin(panel), root = panel.getRootNode();
  panel.hidden = true;
  root.querySelector('.app-shell')?.classList.remove('has-detail');
  if ((restoreFocus && key) || hadFocus) {
    const mapElement = root.querySelector('#map');
    const card = key && root.querySelector(`${cardSelector}[data-key="${CSS.escape(key)}"]`);
    focusFirst(origin === 'marker' ? mapElement : card, root.querySelector('#keyword'), mapElement);
  }
}

const detailLoads = new WeakMap();

// Keep the live region separate from the title and asynchronously rendered prose.
// A new opening invalidates earlier loads, including reopening the same item.
export function announceDetailLoad(panel, tasks) {
  let status = panel.querySelector('#detail-load-status');
  if (!status) {
    status = panel.ownerDocument.createElement('p');
    status.id = 'detail-load-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.setAttribute('aria-atomic', 'true');
    status.style.cssText = 'position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0';
    panel.append(status);
  }
  status.textContent = '';
  const load = {};
  detailLoads.set(panel, load);
  return Promise.allSettled(tasks).then(() => new Promise(resolve => {
    // Even cached responses must finish after the initial title focus.
    requestAnimationFrame(() => {
      const host = panel.getRootNode().host;
      if (detailLoads.get(panel) === load && panel.isConnected && !panel.hidden && !host?.hidden) {
        status.textContent = '詳細情報を更新しました。';
      }
      resolve();
    });
  }));
}
