const KEY = 'gakushuGameHighScore';
const FORMAT = 'dekita-high-score';

export function scoreFromBackup(data) {
  if (!data || data.format !== FORMAT || data.version !== 1 ||
      !Number.isSafeInteger(data.highScore) || data.highScore < 0) {
    throw new Error('できた！のハイスコアファイルを選んでください。');
  }
  return data.highScore;
}

export function currentScore(storage) {
  const score = Number(storage.getItem(KEY));
  return Number.isSafeInteger(score) && score >= 0 ? score : 0;
}

if (typeof document !== 'undefined') {
  const status = document.getElementById('status');
  const showScore = () => {
    document.getElementById('score').textContent = String(currentScore(localStorage));
  };
  try { showScore(); } catch (_) { status.textContent = 'ブラウザの保存領域を利用できません。'; }
  document.getElementById('export').addEventListener('click', () => {
    try {
      const data = {format: FORMAT, version: 1, highScore: currentScore(localStorage)};
      const url = URL.createObjectURL(new Blob([JSON.stringify(data)], {type: 'application/json'}));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'dekita-high-score.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      status.textContent = '保存したファイルを新サイトで読み込んでください。';
    } catch (_) { status.textContent = '保存できませんでした。ブラウザの保存設定を確認してください。'; }
  });
  document.getElementById('import').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 4096) throw new Error('ハイスコアファイルは4KB以下です。ファイルを確認してください。');
      const score = scoreFromBackup(JSON.parse(await file.text()));
      localStorage.setItem(KEY, String(Math.max(currentScore(localStorage), score)));
      showScore();
      status.textContent = 'ハイスコアを引き継ぎました。';
    } catch (error) {
      status.textContent = error instanceof SyntaxError ? 'JSONファイルを読み取れませんでした。' : error.message;
    } finally { event.target.value = ''; }
  });
}
