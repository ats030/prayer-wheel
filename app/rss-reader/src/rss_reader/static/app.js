'use strict';

// Progressive enhancement over server-rendered HTML: filters swap the
// /partials/items fragment, and every slow call goes through the job poller
// so the page never blocks.

const $ = (sel, root = document) => root.querySelector(sel);
const wrap = $('[data-scope]');

function toast(msg, ms) {
  const t = $('#toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), ms || 3000);
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}

// --- job polling ---------------------------------------------------------

const jobBar = $('#jobBar');

function showJob(job) {
  if (!jobBar) return;
  jobBar.hidden = false;
  $('.job-label', jobBar).textContent = job.message || job.kind;
  const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
  $('.job-fill', jobBar).style.width = (job.total ? pct : 15) + '%';
  $('.job-count', jobBar).textContent = job.total ? `${job.done}/${job.total}` : `${job.elapsed}s`;
}

function hideJob() {
  if (jobBar) jobBar.hidden = true;
}

/** Poll a started job to completion. Resolves with the finished job. */
async function awaitJob(job) {
  showJob(job);
  for (;;) {
    await new Promise((r) => setTimeout(r, job.total > 3 ? 700 : 400));
    const res = await fetch(`/api/jobs/${job.id}`, { cache: 'no-store' });
    if (!res.ok) { hideJob(); throw new Error('ジョブの状態を取得できませんでした。'); }
    job = await res.json();
    showJob(job);
    if (job.status !== 'running') break;
  }
  hideJob();
  if (job.status === 'failed') throw new Error(job.message || '処理に失敗しました。');
  return job;
}

/** Start a job endpoint, disable its button while it runs, then await it. */
async function runJob(url, body, btn) {
  if (btn) btn.classList.add('busy');
  try {
    const { job } = await postJSON(url, body);
    return await awaitJob(job);
  } finally {
    if (btn) btn.classList.remove('busy');
  }
}

// --- list filtering ------------------------------------------------------

function currentParams() {
  const params = new URLSearchParams();
  const form = $('#filters');
  if (form) {
    for (const [k, v] of new FormData(form)) {
      if (v !== '') params.append(k, v);
    }
  }
  return params;
}

function fragmentUrl(params, offset) {
  const p = new URLSearchParams(params);
  p.set('scope', wrap.dataset.scope);
  if (wrap.dataset.feed) p.set('feed', wrap.dataset.feed);
  if (wrap.dataset.llm === '1') p.set('llm', '1');
  if (offset) p.set('offset', offset);
  return `/partials/items?${p}`;
}

let reloadToken = 0;

async function reloadList(push = true) {
  const list = $('#list');
  if (!list) return;
  const params = currentParams();
  const token = ++reloadToken;
  list.setAttribute('aria-busy', 'true');
  try {
    const res = await fetch(fragmentUrl(params), { cache: 'no-store' });
    // 入力中に古いレスポンスが後着しても上書きしない
    if (token !== reloadToken) return;
    list.innerHTML = await res.text();
    if (push) {
      // フィルタ以外の状態（表示中フィード・LLMスコア）も URL に残す。
      // 落とすとリロードで別のフィードに飛んでしまう。
      const shown = new URLSearchParams(params);
      if (wrap.dataset.scope === 'feed' && wrap.dataset.feed) shown.set('feed', wrap.dataset.feed);
      if (wrap.dataset.llm === '1') shown.set('llm', '1');
      history.replaceState(null, '', shown.toString() ? `${location.pathname}?${shown}` : location.pathname);
    }
  } catch (err) {
    toast(`一覧を取得できませんでした: ${err.message}`);
  } finally {
    list.removeAttribute('aria-busy');
  }
}

async function loadMore(btn) {
  btn.classList.add('busy');
  try {
    const res = await fetch(fragmentUrl(currentParams(), btn.dataset.offset), { cache: 'no-store' });
    const html = await res.text();
    const doc = document.createRange().createContextualFragment(html);
    $('.items', $('#list')).append(...doc.querySelectorAll('.item'));
    $('#list .list-more').innerHTML = doc.querySelector('.list-more').innerHTML;
    $('#list .list-head').textContent = doc.querySelector('.list-head').textContent;
  } catch (err) {
    toast(`追加の読み込みに失敗しました: ${err.message}`);
    btn.classList.remove('busy');
  }
}

if (wrap) {
  const form = $('#filters');
  if (form && form.id === 'filters' && $('#list')) {
    let debounce;
    form.addEventListener('input', (e) => {
      if (e.target.type === 'text') {
        clearTimeout(debounce);
        debounce = setTimeout(reloadList, 250);
      } else {
        reloadList();
      }
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); reloadList(); });
  }
}

// --- delegated item actions ---------------------------------------------

document.addEventListener('click', async (e) => {
  const more = e.target.closest('.load-more');
  if (more) { loadMore(more); return; }

  const read = e.target.closest('.read-article');
  if (read) {
    const body = read.closest('.item-body').querySelector('.article-body');
    if (!body.hidden) {
      body.hidden = true;
      read.textContent = '本文を読む';
      return;
    }
    if (!body.dataset.loaded) {
      read.classList.add('busy');
      try {
        const res = await fetch(`/api/article?url=${encodeURIComponent(read.dataset.url)}`);
        const data = await res.json();
        body.textContent = data.text || '本文を抽出できませんでした。';
        body.dataset.loaded = '1';
      } catch (err) {
        body.textContent = `記事の取得に失敗しました: ${err.message}`;
      } finally {
        read.classList.remove('busy');
      }
    }
    body.hidden = false;
    read.textContent = '本文を閉じる';
  }
});

// --- feed management -----------------------------------------------------

const refreshAllBtn = $('#refreshAll');
if (refreshAllBtn) {
  refreshAllBtn.addEventListener('click', async () => {
    try {
      const job = await runJob('/api/feeds/refresh-all', {}, refreshAllBtn);
      toast(job.error_count ? `${job.error_count} 件のフィードを更新できませんでした。` : '全フィードを更新しました。');
      location.reload();
    } catch (err) {
      toast(err.message);
    }
  });
}

const refreshFeedBtn = $('#refreshFeed');
if (refreshFeedBtn) {
  refreshFeedBtn.addEventListener('click', async () => {
    try {
      await runJob('/api/feeds/refresh', { url: refreshFeedBtn.dataset.url }, refreshFeedBtn);
      location.reload();
    } catch (err) {
      toast(`更新に失敗しました: ${err.message}`);
    }
  });
}

const addForm = $('#addFeed');
if (addForm) {
  const candidates = $('#candidates');
  const list = $('.candidate-list', candidates);

  async function selectFeed(url, btn) {
    try {
      await runJob('/api/feeds/add', { url }, btn);
      location.href = `/?feed=${encodeURIComponent(url)}`;
    } catch (err) {
      toast(`フィードの追加に失敗しました: ${err.message}`);
    }
  }

  addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = $('#addUrl').value.trim();
    if (!url) return;
    candidates.hidden = true;
    try {
      const job = await runJob('/api/feeds/detect', { url }, $('#addBtn'));
      const feeds = (job.result && job.result.feeds) || [];
      if (feeds.length === 0) {
        toast('フィードが見つかりませんでした。RSS/Atom の URL を直接入力してください。', 5000);
      } else if (feeds.length === 1) {
        await selectFeed(feeds[0], $('#addBtn'));
      } else {
        list.innerHTML = '';
        for (const f of feeds) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'btn btn-secondary btn-xs';
          btn.textContent = f;
          btn.addEventListener('click', () => selectFeed(f, btn));
          list.append(btn);
        }
        candidates.hidden = false;
      }
    } catch (err) {
      toast(err.message, 5000);
    }
  });

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.remove-feed');
    if (!btn) return;
    if (!confirm('このフィードを削除しますか？')) return;
    try {
      await postJSON('/api/feeds/remove', { url: btn.dataset.url });
      location.href = '/';
    } catch (err) {
      toast(`削除に失敗しました: ${err.message}`);
    }
  });
}

// --- bookmark / tags -----------------------------------------------------

const bookmarkBtn = $('#bookmarkBtn');
const tagEditor = $('#tagEditor');
if (bookmarkBtn && tagEditor) {
  const url = bookmarkBtn.dataset.url;
  const input = $('#tagInput');
  const parseTags = () => input.value.split(',').map((t) => t.trim()).filter(Boolean);

  bookmarkBtn.addEventListener('click', () => {
    tagEditor.hidden = !tagEditor.hidden;
    if (!tagEditor.hidden) input.focus();
  });
  $('#tagCancel').addEventListener('click', () => { tagEditor.hidden = true; });

  $('#tagSave').addEventListener('click', async (e) => {
    try {
      await postJSON('/api/bookmarks/save', { url, tags: parseTags() });
      toast('ブックマークを保存しました。');
      location.reload();
    } catch (err) {
      toast(`保存に失敗しました: ${err.message}`);
    }
  });

  $('#tagSuggest').addEventListener('click', async (e) => {
    try {
      const job = await runJob('/api/bookmarks/suggest-tags', { url }, e.currentTarget);
      const tags = (job.result && job.result.tags) || [];
      if (tags.length) input.value = tags.join(', ');
      else toast('タグを生成できませんでした。');
    } catch (err) {
      toast(`タグ生成に失敗しました: ${err.message}`);
    }
  });

  const del = $('#tagDelete');
  if (del) {
    del.addEventListener('click', async () => {
      if (!confirm('このブックマークを削除しますか？')) return;
      try {
        await postJSON('/api/bookmarks/remove', { url });
        location.reload();
      } catch (err) {
        toast(`削除に失敗しました: ${err.message}`);
      }
    });
  }
}

// ブックマーク一覧の行内アクション（開く以外はここで完結させ、再読込を避ける）
document.addEventListener('click', async (e) => {
  const row = e.target.closest('.bm-row');
  if (!row) return;
  const url = row.dataset.url;
  const editor = row.querySelector('.bm-tag-editor');
  const input = row.querySelector('.bm-tag-input');
  const tags = () => input.value.split(',').map((t) => t.trim()).filter(Boolean);

  if (e.target.closest('.bm-tag-edit')) {
    editor.hidden = !editor.hidden;
    if (!editor.hidden) input.focus();
    return;
  }
  if (e.target.closest('.bm-tag-close')) {
    editor.hidden = true;
    return;
  }
  if (e.target.closest('.bm-tag-save')) {
    try {
      await postJSON('/api/bookmarks/save', { url, tags: tags() });
      toast('保存しました。');
      location.reload();
    } catch (err) {
      toast(`保存に失敗しました: ${err.message}`);
    }
    return;
  }
  if (e.target.closest('.bm-tag-suggest')) {
    try {
      const job = await runJob('/api/bookmarks/suggest-tags', { url }, e.target.closest('.bm-tag-suggest'));
      const suggested = (job.result && job.result.tags) || [];
      if (suggested.length) input.value = suggested.join(', ');
      else toast('タグを生成できませんでした。');
    } catch (err) {
      toast(`タグ生成に失敗しました: ${err.message}`);
    }
    return;
  }
  if (e.target.closest('.bm-remove')) {
    if (!confirm('このブックマークを削除しますか？')) return;
    try {
      await postJSON('/api/bookmarks/remove', { url });
      row.remove();
      toast('削除しました。');
    } catch (err) {
      toast(`削除に失敗しました: ${err.message}`);
    }
  }
});

// --- scoring / profile ---------------------------------------------------

const scoreBtn = $('#runScoring');
if (scoreBtn) {
  scoreBtn.addEventListener('click', async () => {
    try {
      const job = await runJob(
        '/api/score',
        { scope: scoreBtn.dataset.scope, url: scoreBtn.dataset.url },
        scoreBtn,
      );
      const r = job.result || {};
      toast(`${r.scored ?? 0}/${r.attempted ?? 0} 件を採点しました。`);
      location.reload();
    } catch (err) {
      toast(`スコアリングに失敗しました: ${err.message}`, 5000);
    }
  });
}

const profileCard = $('#profileCard');
if (profileCard) {
  const body = $('.profile-body', profileCard);
  let loaded = false;
  // プロファイルは開いたときだけ読む（初回表示のコストをゼロにする）
  profileCard.addEventListener('toggle', async () => {
    if (!profileCard.open || loaded) return;
    loaded = true;
    try {
      const res = await fetch('/api/profile');
      const data = await res.json();
      body.textContent = data.profile
        ? (data.source === 'vault' ? `（出典: Obsidian）\n${data.profile}` : data.profile)
        : 'まだ生成されていません。「生成・更新」を押してください。';
    } catch {
      body.textContent = 'プロファイルを取得できませんでした。';
    }
  });

  $('#genProfile').addEventListener('click', async (e) => {
    try {
      const job = await runJob('/api/profile/generate', {}, e.currentTarget);
      const r = job.result || {};
      body.textContent = r.profile || '生成できませんでした。';
      if (r.source === 'vault') toast('Obsidian の索引からプロファイルを生成しました。');
    } catch (err) {
      toast(`生成に失敗しました: ${err.message}`);
    }
  });
}

// --- スコア設定 ----------------------------------------------------------

const weightForm = $('#weightForm');
if (weightForm) {
  const state = $('#saveState');
  const sync = (el) => {
    const out = weightForm.querySelector(`output[for="${el.id}"]`);
    if (out) out.textContent = el.type === 'range' && el.step === '0.1'
      ? Number(el.value).toFixed(1)
      : Number(el.value).toFixed(2);
  };
  weightForm.querySelectorAll('input').forEach(sync);
  weightForm.addEventListener('input', (e) => sync(e.target));

  async function push(url) {
    const values = {};
    for (const [k, v] of new FormData(weightForm)) values[k] = Number(v);
    const data = await postJSON(url, url.endsWith('reset') ? {} : values);
    for (const [k, v] of Object.entries(data.weights || {})) {
      const el = weightForm.querySelector(`[name="${k}"]`);
      if (el) { el.value = v; sync(el); }
    }
    state.textContent = `保存しました（${new Date().toLocaleTimeString()}）`;
  }

  weightForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    try { await push('/api/settings'); } catch (err) { toast(`保存に失敗しました: ${err.message}`); }
  });
  $('#resetWeights').addEventListener('click', async () => {
    try { await push('/api/settings/reset'); toast('既定値に戻しました。'); }
    catch (err) { toast(`失敗しました: ${err.message}`); }
  });
}
