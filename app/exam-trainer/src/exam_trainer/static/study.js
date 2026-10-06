// The study loop: pick a choice, get graded, move on.
//
// Only the next question's text is fetched from the API; the correct index
// stays on the server until an answer is submitted (see /api/exams/{id}/next),
// so the answer is not sitting in the page for anyone reading devtools.
(function () {
  const root = document.getElementById('study');
  if (!root) return;
  const EXAM_ID = root.dataset.examId;
  if (!EXAM_ID) return;

  const nodeFilter = document.getElementById('nodeFilter');
  if (nodeFilter) {
    nodeFilter.addEventListener('change', () => {
      const url = new URL(window.location.href);
      if (nodeFilter.value) url.searchParams.set('node', nodeFilter.value);
      else url.searchParams.delete('node');
      window.location.href = url.toString();
    });
  }

  const card = document.getElementById('card');
  if (!card) return;

  const KEYS = 'ABCDEF';
  let questionId = Number(card.dataset.questionId);
  let shownAt = performance.now();
  let unsure = false;
  let answered = false;
  let loading = false;

  const el = {
    stem: document.getElementById('stem'),
    choices: document.getElementById('choices'),
    result: document.getElementById('result'),
    verdict: document.getElementById('verdict'),
    explanation: document.getElementById('explanation'),
    evidence: document.getElementById('evidence'),
    affiliate: document.getElementById('affiliateCard'),
    affiliateTitle: document.getElementById('affiliateTitle'),
    affiliateReason: document.getElementById('affiliateReason'),
    affiliateLink: document.getElementById('affiliateLink'),
    schedule: document.getElementById('scheduleNote'),
    next: document.getElementById('nextBtn'),
    unsureRow: document.getElementById('unsureRow'),
    unsureBtn: document.getElementById('unsureBtn'),
    hint: document.getElementById('cardHint'),
    status: document.getElementById('studyStatus'),
  };

  document.getElementById('hideAffiliate').addEventListener('click', () => {
    localStorage.setItem('exam-trainer-hide-affiliate', '1');
    el.affiliate.hidden = true;
  });

  function showAffiliate(resource) {
    el.affiliate.hidden = true;
    if (!resource || localStorage.getItem('exam-trainer-hide-affiliate') === '1') return;
    el.affiliateTitle.textContent = resource.title;
    el.affiliateReason.textContent = resource.reason || 'この範囲を体系的に確認できる教材です。';
    el.affiliateLink.href = '/affiliate-resources/' + resource.id + '/click?question_id=' + questionId;
    el.affiliate.hidden = false;
    fetch('/api/affiliate-resources/' + resource.id + '/impression', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question_id: questionId }) }).catch(() => {});
  }

  function setChoicesEnabled(enabled) {
    el.choices.querySelectorAll('.choice').forEach((btn) => { btn.disabled = !enabled; });
  }

  function setStatus(message, error = false) {
    el.status.textContent = message;
    el.status.hidden = !message;
    el.status.classList.toggle('is-error', error);
  }

  el.unsureBtn.addEventListener('click', () => {
    if (answered) return;
    unsure = !unsure;
    el.unsureBtn.textContent = unsure ? '自信がない（記録します）' : '自信がない';
    el.unsureBtn.setAttribute('aria-pressed', String(unsure));
    el.unsureBtn.classList.toggle('btn-secondary', unsure);
    el.unsureBtn.classList.toggle('btn-ghost', !unsure);
  });

  async function submit(index) {
    if (answered) return;
    answered = true;
    setChoicesEnabled(false);
    el.unsureBtn.disabled = true;
    card.setAttribute('aria-busy', 'true');
    setStatus('採点しています…');
    const elapsed = Math.round(performance.now() - shownAt);
    let data;
    try {
      data = await postJSON(`/api/questions/${questionId}/answer`, {
        chosen: index, elapsed_ms: elapsed, unsure,
      });
    } catch (err) {
      setStatus(err.message + '。選択肢をもう一度選んでください。', true);
      answered = false;
      el.unsureBtn.disabled = false;
      setChoicesEnabled(true);
      return;
    } finally {
      card.setAttribute('aria-busy', 'false');
    }
    setStatus('');

    el.choices.querySelectorAll('.choice').forEach((btn) => {
      const i = Number(btn.dataset.index);
      if (i === data.answer || i === index) {
        btn.classList.add(i === data.answer ? 'correct' : 'wrong');
        const mark = document.createElement('span');
        mark.className = 'choice-mark';
        mark.textContent = i === data.answer ? '正解' : '選んだ回答';
        btn.appendChild(mark);
      }
    });

    el.verdict.className = 'verdict ' + (data.correct ? 'correct' : 'wrong');
    el.verdict.textContent = data.correct ? '正解' : '不正解';
    el.explanation.textContent = data.explanation || '解説はありません。';
    if (data.evidence || (data.source_refs || []).length) {
      el.evidence.hidden = false;
      el.evidence.textContent = data.evidence || '';
      (data.source_refs || []).forEach((url) => {
        const a = document.createElement('a');
        a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.textContent = url;
        el.evidence.appendChild(a);
      });
    }
    showAffiliate(data.affiliate_resource);
    const days = data.interval === 1 ? '1日後' : `${data.interval}日後`;
    el.schedule.textContent = `次の復習は${days}`;
    el.result.hidden = false;
    el.unsureRow.hidden = true;
    el.next.focus();
  }

  el.choices.addEventListener('click', (event) => {
    const btn = event.target.closest('.choice');
    if (btn) submit(Number(btn.dataset.index));
  });

  async function loadNext() {
    if (loading || !answered || card.getAttribute('aria-busy') === 'true') return;
    loading = true;
    el.next.disabled = true;
    card.setAttribute('aria-busy', 'true');
    setStatus('次の問題を読み込んでいます…');
    const url = new URL(window.location.href);
    const node = root.dataset.node || '';
    let data;
    try {
      const response = await fetch(
        `/api/exams/${EXAM_ID}/next` + (node ? `?node=${encodeURIComponent(node)}` : '')
      );
      if (!response.ok) throw new Error('次の問題を取得できませんでした');
      data = await response.json();
    } catch (_) {
      setStatus('次の問題を取得できませんでした。「次の問題」で再試行してください。', true);
      return;
    } finally {
      loading = false;
      el.next.disabled = false;
      card.setAttribute('aria-busy', 'false');
    }
    setStatus('');
    if (!data.question) {
      // Nothing left: reload so the empty state (and its reason) is rendered
      // server-side rather than duplicated here.
      window.location.href = url.toString();
      return;
    }
    const q = data.question;
    questionId = q.id;
    card.dataset.questionId = String(q.id);
    el.stem.textContent = q.stem;
    el.choices.replaceChildren();
    (q.choices || []).forEach((choice, index) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'choice';
      btn.dataset.index = String(index);
      const key = document.createElement('span');
      key.className = 'key';
      key.textContent = KEYS[index] || String(index + 1);
      const text = document.createElement('span');
      text.className = 'text';
      text.textContent = choice;
      btn.append(key, text);
      el.choices.appendChild(btn);
    });
    card.querySelector('.study-meta .badge').textContent = q.node_path;
    el.result.hidden = true;
    el.evidence.hidden = true;
    el.evidence.replaceChildren();
    el.affiliate.hidden = true;
    el.unsureRow.hidden = false;
    unsure = false;
    el.unsureBtn.textContent = '自信がない';
    el.unsureBtn.disabled = false;
    el.unsureBtn.setAttribute('aria-pressed', 'false');
    el.unsureBtn.classList.add('btn-ghost');
    el.unsureBtn.classList.remove('btn-secondary');
    answered = false;
    shownAt = performance.now();
    setChoicesEnabled(true);
    document.getElementById('dueCount').textContent = data.counts.due;
    document.getElementById('newCount').textContent = data.counts.new;
    el.hint.textContent = '1問ずつ採点します';
    el.stem.focus();
  }

  el.next.addEventListener('click', loadNext);

  // A/B/C… picks a choice, Enter/Space moves on. Keeps a long session on the
  // keyboard instead of round-tripping to the mouse for every card.
  document.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || event.repeat) return;
    // Selects and fields own letter keys; answer shortcuts still work on buttons.
    if (event.target.closest('input, textarea, select, a, summary, [contenteditable]')) return;
    if (!answered) {
      const index = KEYS.indexOf(event.key.toUpperCase());
      if (index >= 0 && index < el.choices.children.length) {
        event.preventDefault();
        submit(index);
      }
      return;
    }
    // Focused buttons use native activation, so Enter never fires two actions.
    if (event.target.closest('button')) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      loadNext();
    }
  });
})();
