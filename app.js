import { SutraPlayer } from './player.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage');
const dial = $('dial');
const audio = new Audio();
audio.preload = 'auto';
audio.preservesPitch = true;
let player;
let wheelAcc = 0;
let highlighted = null;

function buildWheel() {
  const polar = (r, deg) => {
    const a = deg * Math.PI / 180;
    return [200 + r * Math.sin(a), 200 - r * Math.cos(a)];
  };
  const NS = 'http://www.w3.org/2000/svg';
  for (let i = 0; i < 12; i++) {
    const [x1, y1] = polar(62, i * 30);
    const [x2, y2] = polar(146, i * 30);
    const line = document.createElementNS(NS, 'line');
    for (const [key, value] of Object.entries({ x1, y1, x2, y2, class: 'spoke' })) line.setAttribute(key, value);
    $('spokes').appendChild(line);
    const [cx, cy] = polar(104, i * 30 + 15);
    const dot = document.createElementNS(NS, 'circle');
    for (const [key, value] of Object.entries({ cx, cy, r: 3, class: 'petal' })) dot.setAttribute(key, value);
    $('petals').appendChild(dot);
  }
}

function updateUI() {
  if (!player) return;
  $('counter').textContent = String(player.turns);
  $('rounds').textContent = String(player.completedCycles.size);
  $('queueCount').textContent = String(player.pending.length);
  dial.style.transform = `rotate(${player.angle}deg)`;
  const index = player.currentSequence < 0 ? -1 : player.currentSequence % player.chunks.length;
  if (index !== highlighted) {
    const spans = $('textBlock').querySelectorAll('.chunk');
    spans.forEach((span, i) => {
      span.classList.toggle('active', i === index);
      if (i === index) span.setAttribute('aria-current', 'true');
      else span.removeAttribute('aria-current');
    });
    $('currentLine').textContent = index < 0 ? '輪を回すと、読経が始まります。' : player.chunks[index].text;
    $('currentReading').textContent = index < 0 ? '' : player.chunks[index].reading;
    highlighted = index;
    if (index >= 0) {
      const target = spans[index];
      const block = $('textBlock');
      block.scrollTop = Math.max(0, target.offsetTop - block.clientHeight / 2);
    }
  }
  const position = index + 1;
  $('progressFill').style.width = `${position / player.chunks.length * 100}%`;
  $('progressLabel').textContent = `読み上げ ${position} / ${player.chunks.length} 節`;
  $('pauseBtn').textContent = player.paused ? '再開' : '一時停止';
  $('pauseBtn').disabled = Boolean(player.error) || (!player.active && !player.pending.length);
  $('retryBtn').hidden = !player.error;
  $('voiceBanner').hidden = !player.error;
  $('voiceBanner').textContent = player.error;
  let status = '準備完了。輪を回してください。';
  let mode = 'idle';
  if (player.error) { status = '音声を停止しています。再試行できます。'; mode = 'warn'; }
  else if (player.paused) { status = '一時停止中。再開を押すと続きます。'; mode = 'paused'; }
  else if (player.active) {
    status = player.active.started ? '読経中' : '音声を読み込んでいます…';
    mode = 'speaking';
  } else if (position === player.chunks.length) status = '一巡完了。さらに回すと先頭から続きます。';
  if (player.notice) status = player.notice;
  $('statusText').textContent = status;
  $('statusDot').className = `dot ${mode}`;
}

function turn(direction) {
  if (!player) return;
  if (direction > 0) player.forward();
  else player.backward();
}

stage.addEventListener('wheel', (event) => {
  if (!player || event.ctrlKey) return;
  event.preventDefault();
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? stage.clientHeight : 1;
  const delta = event.deltaY * unit;
  if (Math.sign(delta) !== Math.sign(wheelAcc)) wheelAcc = 0;
  wheelAcc += delta;
  while (Math.abs(wheelAcc) >= 120) {
    const direction = Math.sign(wheelAcc);
    wheelAcc -= direction * 120;
    turn(direction);
  }
}, { passive: false });
stage.addEventListener('click', () => turn(1));
stage.addEventListener('keydown', (event) => {
  if (['ArrowDown', 'PageDown', 'Enter'].includes(event.key)) {
    event.preventDefault(); turn(1);
  } else if (['ArrowUp', 'PageUp'].includes(event.key)) {
    event.preventDefault(); turn(-1);
  } else if (event.code === 'Space') {
    event.preventDefault(); player?.togglePause();
  }
});
$('backBtn').addEventListener('click', () => turn(-1));
$('pauseBtn').addEventListener('click', () => player?.togglePause());
$('retryBtn').addEventListener('click', () => player?.retry());
$('restartBtn').addEventListener('click', () => {
  wheelAcc = 0;
  dial.style.transition = 'none';
  player?.restart();
  void dial.getBoundingClientRect();
  dial.style.transition = '';
});
$('rate').addEventListener('input', () => {
  audio.playbackRate = Number($('rate').value);
  audio.defaultPlaybackRate = audio.playbackRate;
  $('rateOut').textContent = `${audio.playbackRate.toFixed(2).replace(/0$/, '')}×`;
});
$('reloadBtn').addEventListener('click', () => location.reload());

async function initialize() {
  try {
    const response = await fetch('data/sutra.json', { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const sutra = await response.json();
    if (!Array.isArray(sutra.chunks) || !sutra.chunks.length
        || sutra.chunks.some(c => typeof c.text !== 'string' || typeof c.reading !== 'string')) throw new Error('Invalid sutra');
    const chunks = sutra.chunks.map((chunk, i) => ({ ...chunk,
      audio: `audio/${String(i + 1).padStart(2, '0')}.wav`,
    }));
    for (const chunk of chunks) {
      const span = document.createElement('span');
      span.className = 'chunk';
      span.textContent = chunk.text + '　';
      $('textBlock').appendChild(span);
    }
    $('rimTextPath').textContent = chunks.map(c => c.text).join('').slice(0, 60);
    player = new SutraPlayer(chunks, audio, updateUI);
    stage.setAttribute('aria-disabled', 'false');
    $('restartBtn').disabled = false;
    $('backBtn').disabled = false;
    updateUI();
  } catch {
    $('voiceBanner').hidden = false;
    $('voiceBanner').textContent = '経文を読み込めませんでした。接続を確認してページを再読み込みしてください。';
    $('reloadBtn').hidden = false;
    $('statusText').textContent = '読み込みに失敗しました。';
  }
}

buildWheel();
initialize();
