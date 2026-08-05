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

  const el = {
    stem: document.getElementById('stem'),
    choices: document.getElementById('choices'),
    result: document.getElementById('result'),
    verdict: document.getElementById('verdict'),
    explanation: document.getElementById('explanation'),
    evidence: document.getElementById('evidence'),
    schedule: document.getElementById('scheduleNote'),
    next: document.getElementById('nextBtn'),
    unsureRow: document.getElementById('unsureRow'),
    unsureBtn: document.getElementById('unsureBtn'),
    hint: document.getElementById('cardHint'),
  };

  function setChoicesEnabled(enabled) {
    el.choices.querySelectorAll('.choice').forEach((btn) => { btn.disabled = !enabled; });
  }

  el.unsureBtn.addEventListener('click', () => {
    unsure = !unsure;
    el.unsureBtn.textContent = unsure ? '自信がない（記録します）' : '自信がない';
    el.unsureBtn.classList.toggle('btn-secondary', unsure);
    el.unsureBtn.classList.toggle('btn-ghost', !unsure);
  });

  async function submit(index) {
    if (answered) return;
    answered = true;
    setChoicesEnabled(false);
    const elapsed = Math.round(performance.now() - shownAt);
    let data;
    try {
      data = await postJSON(`/api/questions/${questionId}/answer`, {
        chosen: index, elapsed_ms: elapsed, unsure,
      });
    } catch (err) {
      toast(err.message);
      answered = false;
      setChoicesEnabled(true);
      return;
    }

    el.choices.querySelectorAll('.choice').forEach((btn) => {
      const i = Number(btn.dataset.index);
      if (i === data.answer) btn.classList.add('correct');
      else if (i === index) btn.classList.add('wrong');
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
    const url = new URL(window.location.href);
    const node = root.dataset.node || '';
    let data;
    try {
      data = await (await fetch(
        `/api/exams/${EXAM_ID}/next` + (node ? `?node=${encodeURIComponent(node)}` : '')
      )).json();
    } catch (_) {
      toast('次の問題を取得できませんでした');
      return;
    }
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
    el.unsureRow.hidden = false;
    unsure = false;
    el.unsureBtn.textContent = '自信がない';
    el.unsureBtn.classList.add('btn-ghost');
    el.unsureBtn.classList.remove('btn-secondary');
    answered = false;
    shownAt = performance.now();
    setChoicesEnabled(true);
    el.hint.textContent = `復習 ${data.counts.due} · 新規 ${data.counts.new}`;
  }

  el.next.addEventListener('click', loadNext);

  // A/B/C… picks a choice, Enter/Space moves on. Keeps a long session on the
  // keyboard instead of round-tripping to the mouse for every card.
  document.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (!answered) {
      const index = KEYS.indexOf(event.key.toUpperCase());
      if (index >= 0 && index < el.choices.children.length) {
        event.preventDefault();
        submit(index);
      }
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      loadNext();
    }
  });
})();
