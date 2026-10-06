(() => {
  'use strict';
  const questions = JSON.parse(document.getElementById('trial-data').textContent);
  const get = id => document.getElementById(id);
  let index = 0;
  let correct = 0;
  let busy = false;
  let answered = false;
  let missed = new Set();

  function showQuestion(focus) {
    busy = false; answered = false;
    get('trial').hidden = false; get('result').hidden = true;
    get('feedback').hidden = true; get('next').hidden = true; get('trial-error').hidden = true;
    const q = questions[index];
    get('progress').textContent = `${index + 1} / ${questions.length}問 · ${q.category}`;
    get('trial-progress').value = index;
    get('question').textContent = q.stem;
    get('choices').replaceChildren();
    q.choices.forEach((choice, i) => {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = `${'ABCD'[i]}　${choice}`;
      button.addEventListener('click', () => answer(q, i));
      get('choices').append(button);
    });
    if (focus) get('question').focus();
  }

  async function answer(q, chosen) {
    if (busy || answered) return;
    busy = true;
    get('trial-error').hidden = true;
    const buttons = [...get('choices').children];
    buttons.forEach(b => { b.disabled = true; });
    try {
      const response = await fetch('/kouko/trial/answer', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question_id: q.id, chosen}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '解答を確認できませんでした');
      answered = true;
      if (result.correct) correct += 1; else missed.add(q.category);
      buttons[result.answer].classList.add('is-correct');
      if (!result.correct) buttons[chosen].classList.add('is-wrong');
      get('verdict').textContent = `${result.correct ? '正解' : '不正解'} · 正解は${'ABCD'[result.answer]} ${q.choices[result.answer]}`;
      get('explanation').textContent = result.explanation;
      get('source').textContent = `参考：${result.source.title}`; get('source').href = result.source.url;
      get('feedback').hidden = false;
      get('trial-progress').value = index + 1;
      get('next').textContent = index === questions.length - 1 ? '結果と復習ポイントを見る' : '次の問題へ';
      get('next').hidden = false; get('next').focus();
    } catch (error) {
      get('trial-error').textContent = `${error.message}。もう一度選んでください。`;
      get('trial-error').hidden = false;
      buttons.forEach(b => { b.disabled = false; });
    } finally { busy = false; }
  }

  get('next').addEventListener('click', () => {
    if (!answered) return;
    index += 1;
    if (index < questions.length) { showQuestion(true); return; }
    get('trial').hidden = true; get('result').hidden = false;
    get('score').textContent = `${correct} / ${questions.length}問正解`;
    get('review-topics').replaceChildren();
    const p = document.createElement('p');
    p.textContent = missed.size ? `読み返したい分野：${[...missed].join('、')}` : '全問正解でした。解説の用語を自分の言葉でも説明してみましょう。';
    get('review-topics').append(p); get('result-title').focus();
  });
  get('restart').addEventListener('click', () => { index = 0; correct = 0; missed = new Set(); showQuestion(true); });
  showQuestion(false);
})();
