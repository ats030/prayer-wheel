(() => {
  const root = document.getElementById('qualityPage');
  const start = document.getElementById('qualityStart');
  const message = document.getElementById('qualityMessage');
  const button = document.getElementById('startQuality');
  const stateLabels = {queued:'待機中',running:'診断中',done:'診断完了',error:'処理失敗'};
  let timer;
  async function refresh() {
    if (!root.dataset.runId) return;
    try {
      const response = await fetch(`/api/quality/runs/${root.dataset.runId}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '状態を取得できませんでした');
      document.getElementById('qualityProgress').textContent = `${data.completed} / ${data.total}問 · ${stateLabels[data.status]}`;
      if (data.status !== root.dataset.status && ['done','error'].includes(data.status)) {
        window.location.reload(); return;
      }
      if (['queued','running'].includes(data.status)) timer = setTimeout(refresh, 5000);
    } catch (error) {
      message.textContent = `${error.message}。「状態を更新」で再試行できます。`;
    }
  }
  start.addEventListener('submit', async event => {
    event.preventDefault(); button.disabled = true; start.setAttribute('aria-busy','true');
    message.textContent = '診断の保存版を準備しています…';
    try {
      const run = await postJSON('/api/quality/runs', {use_llm:document.getElementById('useLlm').checked});
      window.location.href = `/admin/quality?run_id=${run.id}`;
    } catch (error) { message.textContent = error.message; button.disabled = false; }
    finally { start.setAttribute('aria-busy','false'); }
  });
  document.getElementById('qualityRefresh')?.addEventListener('click', () => {clearTimeout(timer); refresh();});
  document.getElementById('qualityImport')?.addEventListener('submit',async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = document.getElementById('importQuality');
    const file = document.getElementById('reviewFile').files[0];
    if (!file || file.size > 2000000) { message.textContent = '2MB以下の確認済みCSVを選んでください'; return; }
    submit.disabled = true; form.setAttribute('aria-busy','true');
    message.textContent = '確認結果を取り込んでいます…';
    try {
      const result = await postJSON(`/api/quality/runs/${root.dataset.runId}/reviews`, {csv_text:await file.text()});
      message.textContent = `${result.imported}件を取り込みました`;
      window.location.reload();
    } catch (error) { message.textContent = error.message; }
    finally { submit.disabled = false; form.setAttribute('aria-busy','false'); }
  });
  if (['queued','running'].includes(root.dataset.status)) timer = setTimeout(refresh,5000);
})();
