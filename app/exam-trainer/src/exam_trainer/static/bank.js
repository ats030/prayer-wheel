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
