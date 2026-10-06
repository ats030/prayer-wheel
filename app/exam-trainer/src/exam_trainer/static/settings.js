// Exam list and syllabus registration.
(function () {
  const page = document.getElementById('settingsPage');
  if (!page) return;
  const EXAM_ID = page.dataset.examId;

  const addExam = document.getElementById('addExam');
  const examName = document.getElementById('examName');
  const examStatus = document.getElementById('examStatus');
  function examMessage(message, error = false) {
    examStatus.hidden = false;
    examStatus.textContent = message;
    examStatus.classList.toggle('is-error', error);
  }
  async function createExam() {
    if (addExam.disabled) return;
    const name = examName.value.trim();
    if (!name) { examMessage('試験名を入力してください', true); examName.focus(); return; }
    addExam.disabled = true;
    examMessage('試験を追加しています…');
    try {
      const data = await postJSON('/api/exams', { name });
      window.location.href = `/admin/settings?exam_id=${data.id}`;
    } catch (err) {
      examMessage(err.message, true);
      addExam.disabled = false;
    }
  }
  addExam.addEventListener('click', createExam);
  examName.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); createExam(); }
  });

  page.addEventListener('click', async (event) => {
    const btn = event.target.closest('button[data-delete-exam]');
    if (!btn) return;
    if (!window.confirm('この試験を削除しますか？ 問題・解答履歴もすべて消えます。')) return;
    btn.disabled = true;
    try {
      await postJSON(`/api/exams/${btn.dataset.deleteExam}/delete`);
      window.location.href = '/admin/settings';
    } catch (err) {
      examMessage(err.message, true);
      btn.disabled = false;
    }
  });

  const save = document.getElementById('saveSyllabus');
  if (!save || !EXAM_ID) return;
  save.addEventListener('click', async () => {
    const status = document.getElementById('syllabusStatus');
    save.disabled = true;
    status.classList.remove('is-error');
    status.textContent = '保存中…';
    try {
      const data = await postJSON(`/api/exams/${EXAM_ID}/syllabus`, {
        outline: document.getElementById('outline').value,
      });
      status.textContent = `${data.count}項目を登録しました`;

    } catch (err) {
      status.textContent = err.message;
      status.classList.add('is-error');
    } finally {
      save.disabled = false;
    }
  });

  document.getElementById('saveAffiliate').addEventListener('click', async (event) => {
    const btn = event.currentTarget;
    const status = document.getElementById('affiliateStatus');
    btn.disabled = true;
    status.classList.remove('is-error');
    status.textContent = '保存中…';
    try {
      await postJSON('/api/exams/' + EXAM_ID + '/affiliate-resources', {
        node_path: document.getElementById('affiliateNode').value,
        title: document.getElementById('affiliateTitle').value,
        url: document.getElementById('affiliateUrl').value,
        reason: document.getElementById('affiliateReason').value,
      });
      window.location.reload();
    } catch (err) {
      status.textContent = err.message;
      status.classList.add('is-error');
      btn.disabled = false;
    }
  });

  page.addEventListener('click', async (event) => {
    const btn = event.target.closest('button[data-affiliate-active]');
    if (!btn) return;
    btn.disabled = true;
    try {
      await postJSON('/api/affiliate-resources/' + btn.dataset.affiliateActive + '/active',
        { active: btn.dataset.nextActive === '1' });
      window.location.reload();
    } catch (err) {
      const status = document.getElementById('affiliateStatus');
      status.textContent = err.message;
      status.classList.add('is-error');
      btn.disabled = false;
    }
  });
})();
