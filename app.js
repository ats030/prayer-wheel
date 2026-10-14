import { SutraPlayer } from './player.js';
import { characterPosition } from './character-scroll.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage');
const dial = $('dial');
const audio = new Audio();
audio.preload = 'auto';
audio.preservesPitch = true;
let player;
let wheelAcc = 0;
let highlighted = null;
let drumPosition = -1;
let activeCharacter = -1;
let drumFaceCenter = null;
let drumFaceCharacter = null;
let characterTimings = [];
let characterOffsets = [];
let characterEntries = [];
let scrollFrame = null;
let displayedSequence = null;
let displayedCharacter = null;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const DRUM_FACES = 48;
const DRUM_STEP = 360 / DRUM_FACES;

function buildDrum() {
  for (let i = 0; i < DRUM_FACES; i++) {
    const face = document.createElement('div');
    face.className = 'reel-face';
    face.style.setProperty('--face-angle', `${-i * DRUM_STEP}deg`);
    dial.appendChild(face);
  }
}

function renderDrumFaces() {
  const center = Math.round(drumPosition);
  if (center === drumFaceCenter && activeCharacter === drumFaceCharacter) return;
  const slot = ((center % DRUM_FACES) + DRUM_FACES) % DRUM_FACES;
  for (const [i, face] of Array.from(dial.children).entries()) {
    let offset = (i - slot + DRUM_FACES) % DRUM_FACES;
    if (offset > DRUM_FACES / 2) offset -= DRUM_FACES;
    const ordinal = center + offset;
    const entry = ordinal >= 0 ? characterEntries[ordinal % characterEntries.length] : null;
    face.textContent = entry?.text ?? (ordinal === -1 ? '心経を回す' : '');
    face.classList.toggle('is-selected', ordinal === activeCharacter);
    face.classList.toggle('is-intro', ordinal < 0);
    face.dataset.sequence = String(ordinal);
    face.dataset.section = String(entry ? Math.floor(ordinal / characterEntries.length) * player.chunks.length + entry.section : -1);
    face.dataset.character = String(entry?.index ?? -1);
  }
  drumFaceCenter = center;
  drumFaceCharacter = activeCharacter;
}

function renderDrum() {
  if (!player) return;
  const sequence = player.currentSequence;
  // A new source may reset currentTime while loading. Hold the last spoken position.
  const ownsClock = Boolean(player.active?.started && player.active.sequence === sequence);
  if (sequence < 0) {
    drumPosition = activeCharacter = -1;
  } else if (ownsClock) {
    const section = sequence % player.chunks.length;
    const cue = characterPosition(characterTimings[section].characters, audio.currentTime, reducedMotion.matches, characterTimings[section].duration);
    const base = Math.floor(sequence / player.chunks.length) * characterEntries.length + characterOffsets[section];
    drumPosition = base + cue.position;
    activeCharacter = base + cue.index;
  }
  const rotation = `${drumPosition * DRUM_STEP}deg`;
  if (dial.style.getPropertyValue('--drum-turn') !== rotation) dial.style.setProperty('--drum-turn', rotation);
  renderDrumFaces();
  const entry = activeCharacter >= 0 ? characterEntries[activeCharacter % characterEntries.length] : null;
  if (sequence !== displayedSequence || activeCharacter !== displayedCharacter) {
    $('drumPosition').textContent = !entry ? `0 / ${player.chunks.length} 節`
      : `${sequence % player.chunks.length + 1} / ${player.chunks.length} 節 · ${entry.index + 1} / ${characterTimings[entry.section].characters.length} 字`;
    $('drumSelection').textContent = entry ? `読み上げの文字：${entry.text}（${entry.reading}）`
      : '読み上げに合わせて、経文が一文字ずつ流れます。';
    displayedSequence = sequence;
    displayedCharacter = activeCharacter;
  }
  const running = ownsClock && !player.paused && !player.error && !audio.paused && !audio.ended;
  dial.dataset.moving = String(running && !reducedMotion.matches);
  if (running && scrollFrame === null) {
    scrollFrame = requestAnimationFrame(() => { scrollFrame = null; renderDrum(); });
  } else if (!running && scrollFrame !== null) {
    cancelAnimationFrame(scrollFrame);
    scrollFrame = null;
  }
}

for (const event of ['timeupdate', 'pause', 'waiting', 'stalled', 'ended', 'ratechange', 'seeking']) {
  audio.addEventListener(event, renderDrum);
}
reducedMotion.addEventListener('change', renderDrum);

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
    const sutraText = await response.text();
    const sutra = JSON.parse(sutraText);
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
    const timingResponse = await fetch('data/character-timing.json', { cache: 'no-store', signal: AbortSignal.timeout(15000) });
    if (!timingResponse.ok) throw new Error('Character timing unavailable');
    const timings = await timingResponse.json();
    const sutraDigest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(sutraText)))].map(b => b.toString(16).padStart(2, '0')).join('');
    if (timings.sutraSha256 !== sutraDigest) throw new Error('Character timing source mismatch');
    if (timings.version !== 1 || timings.sections.length !== chunks.length) throw new Error('Invalid character timing');
    characterTimings = timings.sections;
    for (const [section, timing] of characterTimings.entries()) {
      if (!/^[a-f0-9]{64}$/.test(timing.audioSha256)
          || timing.file !== `synced/${timing.audioSha256}/${String(section + 1).padStart(2, '0')}.wav`) {
        throw new Error('Character audio version mismatch');
      }
      chunks[section].audio = `audio/${timing.file}`;
      if (!timing.characters.length || timing.characters.map(c => c.text).join('') !== chunks[section].text.replaceAll('　', '')) {
        throw new Error('Character text mismatch');
      }
      if (!Number.isFinite(timing.duration) || !timing.characters.every((cue, index) =>
        Number.isFinite(cue.start) && Number.isFinite(cue.end) && cue.start >= 0 && cue.end > cue.start
        && cue.end <= timing.duration && (index === 0 || cue.start >= timing.characters[index - 1].end))) {
        throw new Error('Invalid character intervals');
      }
      characterOffsets.push(characterEntries.length);
      timing.characters.forEach((cue, index) => characterEntries.push({ ...cue, section, index }));
      characterEntries.push({ text: '', reading: '', section, index: -1 });
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
