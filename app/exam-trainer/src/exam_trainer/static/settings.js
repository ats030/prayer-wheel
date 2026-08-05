// Exam list and syllabus registration.
(function () {
  const page = document.getElementById('settingsPage');
  if (!page) return;
  const EXAM_ID = page.dataset.examId;

  const addExam = document.getElementById('addExam');
  const examName = document.getElementById('examName');
  async function createExam() {
    const name = examName.value.trim();
    if (!name) { toast('試験名を入力してください'); examName.focus(); return; }
    addExam.disabled = true;
    try {
      const data = await postJSON('/api/exams', { name });
      window.location.href = `/settings?exam_id=${data.id}`;
    } catch (err) {
      toast(err.message);
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
      window.location.href = '/settings';
    } catch (err) {
      toast(err.message);
      btn.disabled = false;
    }
  });

  const save = document.getElementById('saveSyllabus');
  if (!save || !EXAM_ID) return;
  save.addEventListener('click', async () => {
    const status = document.getElementById('syllabusStatus');
    save.disabled = true;
    status.textContent = '保存中…';
    try {
      const data = await postJSON(`/api/exams/${EXAM_ID}/syllabus`, {
        outline: document.getElementById('outline').value,
      });
      status.textContent = `${data.count}項目を登録しました`;
      toast('シラバスを保存しました');
    } catch (err) {
      status.textContent = err.message;
    } finally {
      save.disabled = false;
    }
  });
})();
