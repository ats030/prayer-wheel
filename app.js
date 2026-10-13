import { SutraPlayer } from './player.js';
import { DrumMotion } from './drum-motion.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage');
const dial = $('dial');
const audio = new Audio();
audio.preload = 'auto';
audio.preservesPitch = true;
let player;
let wheelAcc = 0;
let highlighted = null;
let drumSequence = null;
let drumFaceCenter = null;
let drumFaceSequence = null;
const DRUM_FACES = 16;
const DRUM_STEP = 360 / DRUM_FACES;
const drumMotion = new DrumMotion(dial, -DRUM_STEP);
drumMotion.onDraw = renderDrumFaces;

function buildDrum() {
  for (let i = 0; i < DRUM_FACES; i++) {
    const face = document.createElement('div');
    face.className = 'reel-face';
    face.style.setProperty('--face-angle', `${-i * DRUM_STEP}deg`);
    dial.appendChild(face);
  }
}

function renderDrumFaces() {
  if (!player) return;
  const sequence = player.nextSequence - 1;
  // Recycle hidden faces around the physical angle, even during large rewinds.
  const center = Math.round(drumMotion.angle / DRUM_STEP);
  if (center === drumFaceCenter && sequence === drumFaceSequence) return;
  const slot = ((center % DRUM_FACES) + DRUM_FACES) % DRUM_FACES;
  for (const [i, face] of Array.from(dial.children).entries()) {
    let offset = (i - slot + DRUM_FACES) % DRUM_FACES;
    if (offset > DRUM_FACES / 2) offset -= DRUM_FACES;
    const ordinal = center + offset;
    const text = ordinal >= 0 ? player.chunks[ordinal % player.chunks.length].text
      : ordinal === -1 ? '心経を回す' : '';
    face.textContent = text;
    face.classList.toggle('is-selected', ordinal === sequence);
    face.classList.toggle('is-long', text.length > 14);
    face.dataset.sequence = String(ordinal);
  }
  drumFaceCenter = center;
  drumFaceSequence = sequence;
}

function renderDrum() {
  // The player's next position already includes reservations and rewinds.
  const sequence = player.nextSequence - 1;
  if (sequence === drumSequence) return;
  drumMotion.moveTo(sequence * DRUM_STEP);
  renderDrumFaces();
  const position = sequence < 0 ? 0 : sequence % player.chunks.length + 1;
  $('drumPosition').textContent = `${position} / ${player.chunks.length} 節`;
  $('drumSelection').textContent = sequence < 0
    ? '中央は操作した節。音声は順番に読み上げます。'
    : `操作した節：${player.chunks[position - 1].text}。音声は順番に読み上げます。`;
  drumSequence = sequence;
}

function updateUI() {
  if (!player) return;
  $('counter').textContent = String(player.turns);
  $('rounds').textContent = String(player.completedCycles.size);
  $('queueCount').textContent = String(player.pending.length);
  renderDrum();
  const index = player.currentSequence < 0 ? -1 : player.currentSequence % player.chunks.length;
  const finishedCycle = !player.active && index === player.chunks.length - 1
    && player.completedCycles.has(Math.floor(player.currentSequence / player.chunks.length));
  stage.dataset.state = player.error ? 'error' : player.paused ? 'paused'
    : player.active && !player.active.started ? 'loading'
    : finishedCycle ? 'success' : 'ready';
  if (index !== highlighted) {
    const spans = $('textBlock').querySelectorAll('.chunk');
    spans.forEach((span, i) => {
      span.classList.toggle('active', i === index);
      if (i === index) span.setAttribute('aria-current', 'true');
      else span.removeAttribute('aria-current');
    });
    $('currentLine').textContent = index < 0 ? 'ドラムを回すと、読経が始まります。' : player.chunks[index].text;
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
  let status = '準備完了。ドラムを回してください。';
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
  drumMotion.snap(-DRUM_STEP);
  player?.restart();
});
$('rate').addEventListener('input', () => {
  audio.playbackRate = Number($('rate').value);
  audio.defaultPlaybackRate = audio.playbackRate;
  $('rateOut').textContent = `${audio.playbackRate.toFixed(2).replace(/0$/, '')}×`;
});
$('reloadBtn').addEventListener('click', () => location.reload());

async function initialize() {
  try {
    const response = await fetch('data/sutra-sections.json', { signal: AbortSignal.timeout(15000) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const sutra = await response.json();
    if (!Array.isArray(sutra.chunks) || !sutra.chunks.length
        || sutra.chunks.some(c => typeof c.text !== 'string' || typeof c.reading !== 'string')) throw new Error('Invalid sutra');
    if (sutra.audioDirectory !== 'audio/sections') throw new Error('Invalid audio directory');
    const chunks = sutra.chunks.map((chunk, i) => ({ ...chunk,
      audio: `${sutra.audioDirectory}/${String(i + 1).padStart(2, '0')}.wav`,
    }));
    for (const chunk of chunks) {
      const span = document.createElement('span');
      span.className = 'chunk';
      span.textContent = chunk.text + '　';
      $('textBlock').appendChild(span);
    }
    player = new SutraPlayer(chunks, audio, updateUI);
    stage.setAttribute('aria-disabled', 'false');
    $('restartBtn').disabled = false;
    $('backBtn').disabled = false;
    updateUI();
  } catch {
    stage.dataset.state = 'error';
    $('voiceBanner').hidden = false;
    $('voiceBanner').textContent = '経文を読み込めませんでした。接続を確認してページを再読み込みしてください。';
    $('reloadBtn').hidden = false;
    $('statusText').textContent = '読み込みに失敗しました。';
  }
}

buildDrum();
initialize();
