(() => {
  'use strict';
  // The page is built once per deploy; follow the reader's date instead.
  const pad = n => String(n).padStart(2, '0');
  const now = new Date();
  const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const month = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
  const thisMonth = month(now);
  const nextMonth = month(new Date(now.getFullYear(), now.getMonth() + 1, 1));
  const label = m => `${Number(m.slice(0, 4))}年${Number(m.slice(5))}月`;
  for (const item of document.querySelectorAll('li[data-end]')) item.hidden = item.dataset.end < today;
  for (const section of document.querySelectorAll('section[data-month]')) {
    section.hidden = section.dataset.month < thisMonth;
    const empty = section.querySelector('.calendar-empty');
    empty.hidden = Boolean(section.querySelector('li[data-end]:not([hidden])'));
  }
  const main = document.querySelector('main');
  let previous = document.querySelector('.story-lead');
  for (const [id, prefix, m] of [['this-month-link', '今月', thisMonth], ['next-month-link', '来月', nextMonth]]) {
    let section = document.querySelector(`section[data-month="${m}"]`);
    if (!section) {
      // Past the built range: say so instead of showing a stale month.
      section = document.createElement('section');
      section.className = 'story-reading';
      section.id = 'm-' + m;
      section.dataset.month = m;
      section.innerHTML = `<h2>${label(m)}</h2><p class="calendar-empty">この月に日程が確定している祭りはまだ登録されていません。</p>`;
      main.insertBefore(section, previous.nextSibling);
    }
    previous = section;
    const link = document.getElementById(id);
    link.href = '#' + section.id;
    link.textContent = `${prefix}（${label(m)}）`;
  }
})();
