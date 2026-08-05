// Question bank: review held items, promote or drop them, add one by hand.
(function () {
  const page = document.getElementById('bankPage');
  if (!page) return;
  const EXAM_ID = page.dataset.examId;

  // Status changes and deletes reload the page: the tab counts in the header
  // come from the server, and keeping them right client-side would mean
  // duplicating the counting rules here.
  page.addEventListener('click', async (event) => {
    const btn = event.target.closest('button[data-action]');
    if (!btn) return;
    const row = btn.closest('.q-row');
    const id = row && row.dataset.questionId;
    if (!id) return;
    const action = btn.dataset.action;
    if (action === 'delete' && !window.confirm('この問題を削除しますか？ 解答履歴も一緒に消えます。')) return;
    btn.disabled = true;
    try {
      if (action === 'delete') {
        await postJSON(`/api/questions/${id}/delete`);
      } else {
        await postJSON(`/api/questions/${id}/status`, { status: action });
      }
      window.location.reload();
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  });

  // --- generation jobs ---------------------------------------------------
  const genModal = document.getElementById('generateModal');
  const genBtn = document.getElementById('generateBtn');
  const panel = document.getElementById('jobPanel');
  let pollTimer = null;

  function renderJobs(items) {
    if (!panel) return;
    const active = (items || []).filter((job) => job.status === 'queued' || job.status === 'running');
    // items arrives newest-first. Show the job actually running; with none
    // running, show the oldest queued one, because that is the one about to
    // start. Taking active[0] named the most recently queued node instead,
    // which reads as "generating 2.2" while 4.1 is the one being worked on.
    const latest = active.find((job) => job.status === 'running')
      || active[active.length - 1]
      || (items || [])[0];
    if (!latest) { panel.hidden = true; return; }
    panel.hidden = false;
    const title = document.getElementById('jobTitle');
    const status = document.getElementById('jobStatus');
    if (latest.status === 'error') {
      title.textContent = `生成に失敗しました（${latest.node_path}）`;
      status.textContent = latest.error || 'もう一度実行してください。';
    } else if (latest.status === 'done') {
      title.textContent = `生成が終わりました（${latest.node_path}）`;
      status.textContent = latest.status_text || '';
    } else {
      // With a bulk run the queue is several deep; showing only the running one
      // makes it look like nothing else was accepted.
      const waiting = active.length - 1;
      title.textContent = `生成中（${latest.node_path}）`
        + (waiting > 0 ? ` — 他に${waiting}項目が待機中` : '');
      status.textContent = latest.status_text || '待機中';
    }
    clearTimeout(pollTimer);
    // Only keep polling while something is actually running; a finished job
    // does not need a timer waking the page up forever.
    if (active.length) pollTimer = setTimeout(pollJobs, 4000);
  }

  async function pollJobs() {
    if (!EXAM_ID) return;
    try {
      const data = await (await fetch(`/api/exams/${EXAM_ID}/jobs`)).json();
      const before = document.getElementById('jobTitle').textContent;
      renderJobs(data.items);
      // A run that just finished has added questions the list doesn't show yet.
      if (before.startsWith('生成中') && !document.getElementById('jobTitle').textContent.startsWith('生成中')) {
        window.location.reload();
      }
    } catch (_) {
      clearTimeout(pollTimer);
      pollTimer = setTimeout(pollJobs, 8000);
    }
  }

  if (panel) {
    document.getElementById('jobRefresh').addEventListener('click', () => window.location.reload());
    pollJobs();
  }

  if (genBtn && genModal) {
    const preview = document.getElementById('genPreview');
    const nodeField = document.getElementById('genNodeField');
    const limitField = document.getElementById('genLimitField');
    const scopeInputs = Array.from(genModal.querySelectorAll('input[name="genScope"]'));
    const scopeOf = () => (scopeInputs.find((el) => el.checked) || {}).value || 'one';
    const numberOf = (id, fallback) => Number(document.getElementById(id).value) || fallback;

    // Show which nodes a bulk run would take, so the queue is never a surprise.
    async function refreshPreview() {
      const bulk = scopeOf() === 'missing';
      nodeField.hidden = bulk;
      limitField.hidden = !bulk;
      preview.hidden = !bulk;
      if (!bulk) return;
      preview.textContent = '対象を数えています…';
      try {
        const params = new URLSearchParams({
          target: String(numberOf('genTarget', 5)),
          limit: String(numberOf('genLimit', 8)),
        });
        const data = await (await fetch(`/api/exams/${EXAM_ID}/missing?${params}`)).json();
        if (!data.count) {
          preview.textContent = 'すべての項目が目標に達しています。';
          return;
        }
        const lines = data.items.map((item) => {
          const score = item.accuracy === null ? '未挑戦' : `正答率${Math.round(item.accuracy * 100)}%`;
          return `${item.path} ${item.title}（${score} · ${item.have}問）`;
        });
        preview.textContent = `${data.count}項目を弱点の順に積みます: ` + lines.join(' / ');
      } catch (_) {
        preview.textContent = '対象を数えられませんでした。';
      }
    }

    scopeInputs.forEach((el) => el.addEventListener('change', refreshPreview));
    ['genTarget', 'genLimit'].forEach((id) => {
      document.getElementById(id).addEventListener('change', refreshPreview);
    });

    function openGenerate() {
      document.getElementById('genStatus').textContent = '';
      genModal.classList.add('show');
      refreshPreview();
    }
    genBtn.addEventListener('click', openGenerate);
    // Arrived from a weakness branch with no questions: the node is already
    // selected server-side, so open straight onto it.
    if (page.dataset.openGenerate && !genBtn.disabled) openGenerate();
    document.getElementById('genCancel').addEventListener('click', () => genModal.classList.remove('show'));
    genModal.addEventListener('click', (event) => {
      if (event.target === genModal) genModal.classList.remove('show');
    });
    document.getElementById('genConfirm').addEventListener('click', async () => {
      const status = document.getElementById('genStatus');
      const btn = document.getElementById('genConfirm');
      const node = document.getElementById('genNode');
      const bulk = scopeOf() === 'missing';
      if (!bulk && (!node || !node.value)) {
        // Two different situations produce an empty value: nothing registered
        // yet, or the placeholder still selected. Saying the wrong one sends
        // the user to the wrong screen.
        status.textContent = node && node.options.length > 1
          ? 'シラバス項目を選んでください'
          : 'シラバスを先に登録してください';
        if (node) node.focus();
        return;
      }
      btn.disabled = true;
      status.textContent = 'ジョブを登録中…';
      try {
        const target = numberOf('genTarget', 5);
        if (bulk) {
          const data = await postJSON(`/api/exams/${EXAM_ID}/generate-missing`, {
            target, limit: numberOf('genLimit', 8),
          });
          toast(`${data.count}項目をキューに積みました。画面を閉じても続きます`, 4000);
        } else {
          await postJSON(`/api/exams/${EXAM_ID}/generate`, { node_path: node.value, target });
          toast('生成を開始しました。画面を閉じても続きます');
        }
        genModal.classList.remove('show');
        pollJobs();
      } catch (err) {
        status.textContent = err.message;
      } finally {
        btn.disabled = false;
      }
    });
  }

  const modal = document.getElementById('addModal');
  const addBtn = document.getElementById('addBtn');
  if (!modal || !addBtn) return;

  addBtn.addEventListener('click', () => {
    document.getElementById('addStatus').textContent = '';
    modal.classList.add('show');
    document.getElementById('qStem').focus();
  });
  document.getElementById('addCancel').addEventListener('click', () => modal.classList.remove('show'));
  modal.addEventListener('click', (event) => {
    if (event.target === modal) modal.classList.remove('show');
  });

  const lines = (id) => document.getElementById(id).value
    .split('\n').map((line) => line.trim()).filter(Boolean);

  document.getElementById('addConfirm').addEventListener('click', async () => {
    const status = document.getElementById('addStatus');
    const choices = lines('qChoices');
    const answerKey = document.getElementById('qAnswer').value.trim().toUpperCase();
    const answer = 'ABCDEF'.indexOf(answerKey);
    if (answer < 0) { status.textContent = '正解は A〜F で指定してください'; return; }
    const btn = document.getElementById('addConfirm');
    btn.disabled = true;
    status.textContent = '保存中…';
    try {
      await postJSON(`/api/exams/${EXAM_ID}/questions`, {
        node_path: document.getElementById('qNode').value,
        stem: document.getElementById('qStem').value,
        choices,
        answer,
        explanation: document.getElementById('qExplanation').value,
        source_refs: lines('qSources'),
        // Hand-written questions skip the model gate: a human already vouched
        // for them, so they are served straight away.
        status: 'verified',
      });
      window.location.reload();
    } catch (err) {
      status.textContent = err.message;
      btn.disabled = false;
    }
  });
})();
