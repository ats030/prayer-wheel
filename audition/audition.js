const audios = [...document.querySelectorAll('audio')];
const status = document.querySelector('#auditionStatus');
for (const audio of audios) {
  const label = audio.getAttribute('aria-label');
  audio.addEventListener('play', () => {
    for (const other of audios) if (other !== audio) other.pause();
    status.textContent = `${label}を再生しています。`;
  });
  audio.addEventListener('pause', () => {
    if (audios.every(item => item.paused)) status.textContent = '一時停止中です。再生ボタンで続けられます。';
  });
  audio.addEventListener('ended', () => { status.textContent = `${label}の再生が終わりました。`; });
  const showError = () => {
    status.textContent = `${label}を読み込めませんでした。ページを再読み込みするか、音声のリンクを開いてください。`;
  };
  audio.addEventListener('error', showError);
  if (audio.error) showError();
}
