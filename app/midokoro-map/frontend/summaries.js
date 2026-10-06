// Render only the verified, generated section payload. No source prose fallback.
export function summaryRenderer(context) {
  const {document, fetch} = context;
  const pending = new Map();
  const escape = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function sourceMarkup(section) {
    let url;
    try { url = new URL(section.source_url); } catch { return ''; }
    if (!['http:','https:'].includes(url.protocol)) return '';
    const wiki = url.hostname === 'ja.wikipedia.org';
    return `AIによる要約 · <a href="${escape(url.href)}" target="_blank" rel="noopener noreferrer">${wiki?'Wikipedia':'出典'}↗</a>${wiki?' · <a href="https://creativecommons.org/licenses/by-sa/4.0/deed.ja" target="_blank" rel="noopener noreferrer">CC BY-SA 4.0↗</a>':''}`;
  }
  return async (id, isCurrent) => {
    if (!pending.has(id)) {
      pending.set(id, fetch('/api/summary/'+encodeURIComponent(id)).then(response => {
        if (!response.ok) throw new Error('summary unavailable');
        return response.json();
      }).catch(error => { pending.delete(id); throw error; }));
    }
    let data;
    try { data = await pending.get(id); } catch {
      if (isCurrent()) {
        const body = document.querySelector('.detail-description');
        if (body) body.textContent = '要約を読み込めませんでした。もう一度開いてください。';
        for (const key of ['history','remains','access','highlights','food','efficacy','tourism','flow']) {
          const status = document.querySelector(`#detail-${key}-status`);
          if (status) status.textContent = '要約を読み込めませんでした。もう一度開いてください。';
        }
      }
      return;
    }
    if (!isCurrent()) return;
    for (const [key, section] of Object.entries(data.sections || {})) {
      const body = document.querySelector(key === 'about'?'.detail-description':`#detail-${key}-body`);
      const status = document.querySelector(key === 'about'?'.detail-description-status':`#detail-${key}-status`);
      const container = key === 'about'?body?.closest('.detail-section'):document.querySelector(`#detail-${key}-section`);
      if (!body || !container) continue;
      container.hidden = section.status === 'no_source';
      if (container.hidden) { body.textContent = ''; if (status) status.textContent = ''; continue; }
      const rows = (section.items || []).map(row => `<div><dt>${escape(row.label)}</dt><dd>${escape([row.from&&row.to?`${row.from} → ${row.to}`:'',row.value].filter(Boolean).join(' '))}</dd></div>`).join('');
      body.innerHTML = (section.summary?`<span class="detail-summary">${escape(section.summary)}</span>`:'')+(rows?`<dl class="section-items">${rows}</dl>`:'');
      if (status) status.innerHTML = sourceMarkup(section);
    }
  };
}
