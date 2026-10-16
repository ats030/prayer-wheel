import { SutraPlayer } from './player.js';
import { characterPosition } from './character-scroll.js';
import { modernTranslations } from './modern-translations.js';

const $ = (id) => document.getElementById(id);
const stage = $('stage');
const dial = $('dial');
const audio = new Audio();
audio.preload = 'auto';
audio.preservesPitch = true;
const sutras = {
  hannya: { title: '般若心経', source: 'data/sutra-sections.json', timing: 'data/character-timing.json', audioDirectory: 'audio/sections' },
  enmei: { title: '延命十句観音経', source: 'data/enmei.json', timing: 'data/enmei-timing.json', audioDirectory: 'audio/enmei' },
  komyo: { title: '光明真言', source: 'data/komyo.json', timing: 'data/komyo-timing.json', audioDirectory: 'audio/komyo' },
  hachidai: { title: '仏説八大人覚経', source: 'data/hachidai.json', timing: 'data/hachidai-timing.json', audioDirectory: 'audio/hachidai' },
  amida: { title: '仏説阿弥陀経', source: 'data/amida.json', timing: 'data/amida-timing.json', audioDirectory: 'audio/amida' },
};
let player;
let startedByUser = false;
let loadVersion = 0;
let loadController;
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
let audioStalled = false;
let stalledAt = 0;
const preparedAudio = new Map();
const audioObjectUrls = new Set();
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const DRUM_FACES = 48;
const DRUM_STEP = 360 / DRUM_FACES;

// Use page scrolling only when fixed controls leave too little readable space.
function fitReaderViewport() {
  const page = document.querySelector('.page');
  const grid = document.querySelector('.grid');
  const pageStyle = getComputedStyle(page);
  const gridStyle = getComputedStyle(grid);
  const fixed = ['.top', '.secondary', '.reading-bottom', '#voiceBanner', '#reloadBtn', 'noscript']
    .reduce((sum, selector) => sum + (document.querySelector(selector)?.getBoundingClientRect().height || 0), 0);
  const required = fixed + parseFloat(pageStyle.paddingTop) + parseFloat(pageStyle.paddingBottom)
    + parseFloat(gridStyle.marginTop) + parseFloat(gridStyle.marginBottom) + 80;
  document.body.classList.toggle('is-constrained', required > window.innerHeight);
}
let fitFrame;
const fitObserver = new ResizeObserver(() => {
  cancelAnimationFrame(fitFrame);
  fitFrame = requestAnimationFrame(fitReaderViewport);
});
for (const selector of ['.top', '.secondary', '.reading-bottom', '#voiceBanner', '#reloadBtn']) {
  fitObserver.observe(document.querySelector(selector));
}
window.addEventListener('resize', fitReaderViewport);

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
    face.textContent = entry?.text ?? '';
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
  const running = ownsClock && !player.paused && !player.error && !audioStalled
    && !audio.paused && !audio.ended;
  const crossingBoundary = sequence >= 0 && (audio.ended && player.pending.length > 0
    || player.active && !player.active.started && player.active.sequence === sequence + 1);
  const moving = Boolean((running || crossingBoundary) && !player.paused
    && !player.error && !audioStalled && !reducedMotion.matches);
  const settling = Boolean(audio.ended && !player.active && !player.pending.length
    && !player.paused && !player.error && !audioStalled && !reducedMotion.matches);
  if (!moving && !settling && dial.dataset.moving === 'true') {
    // Disabling a CSS transition would otherwise snap to its destination.
    dial.style.transform = getComputedStyle(dial).transform;
  }
  if (moving || settling || reducedMotion.matches || sequence < 0) dial.style.removeProperty('transform');
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
  dial.dataset.moving = String(moving);
  dial.dataset.settling = String(settling);
  if (running && scrollFrame === null) {
    scrollFrame = requestAnimationFrame(() => { scrollFrame = null; renderDrum(); });
  } else if (!running && scrollFrame !== null) {
    cancelAnimationFrame(scrollFrame);
    scrollFrame = null;
  }
}

for (const event of ['timeupdate', 'pause', 'waiting', 'stalled', 'ended', 'ratechange', 'seeking']) {
  audio.addEventListener(event, () => {
    if (event === 'stalled' || event === 'waiting' && player?.active?.started) {
      audioStalled = true;
      stalledAt = audio.currentTime;
    }
    // A stalled network request can recover using buffered data without playing.
    if (event === 'timeupdate' && audio.currentTime > stalledAt
        && !audio.paused && !audio.ended) audioStalled = false;
    renderDrum();
  });
}
audio.addEventListener('playing', () => { audioStalled = false; renderDrum(); });
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
    $('readingCopy').scrollTop = 0;
    const spans = $('textBlock').querySelectorAll('.chunk');
    spans.forEach((span, i) => {
      span.classList.toggle('active', i === index);
      if (i === index) span.setAttribute('aria-current', 'true');
      else span.removeAttribute('aria-current');
    });
    $('currentLine').textContent = index < 0 ? 'タップして開始' : player.chunks[index].text;
    $('currentReading').textContent = index < 0 ? '' : player.chunks[index].reading;
    $('currentTranslation').textContent = index < 0 ? '' : player.chunks[index].translation;
    $('translationBlock').hidden = index < 0;
    $('currentLine').classList.toggle('is-waiting', index < 0);
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
  $('voiceBanner').hidden = !player.error;
  $('voiceBanner').textContent = player.error;
  $('stageHint').textContent = startedByUser ? 'タップで次へ' : 'タップして開始';
  let status = startedByUser ? '準備完了。マニ車を回してください。' : 'マニ車をタップしてください。';
  let mode = 'idle';
  if (player.error) { status = 'マニ車をタップして再開してください。'; mode = 'warn'; }
  else if (player.paused) { status = '一時停止中。Spaceで再開できます。'; mode = 'paused'; }
  else if (player.active) {
    status = player.active.started ? '読経中' : '音声を読み込んでいます…';
    mode = 'speaking';
  } else if (position === player.chunks.length) status = '一巡完了。さらに回すと先頭から続きます。';
  if (player.notice) status = player.notice;
  $('statusText').textContent = status;
  $('statusDot').className = `dot ${mode}`;
}

// Also enforce exclusive panels on browsers without named-details support.
for (const panel of document.querySelectorAll('.secondary details')) {
  panel.addEventListener('toggle', () => {
    if (!panel.open) return;
    for (const other of document.querySelectorAll('.secondary details')) {
      if (other !== panel) other.open = false;
    }
  });
}

// A closed details has no layout; align the current passage after it opens.
$('sutraDetails').addEventListener('toggle', () => {
  if (!$('sutraDetails').open) return;
  const target = $('textBlock').querySelector('.chunk.active');
  if (target) $('textBlock').scrollTop = Math.max(0, target.offsetTop - $('textBlock').clientHeight / 2);
});

function prepareAudio(sequence) {
  const owner = player;
  if (!owner || sequence < 0) return;
  const chunk = owner.chunks[sequence % owner.chunks.length];
  if (preparedAudio.has(chunk)) return;
  const signal = loadController.signal;
  const task = fetch(chunk.audio, { signal, cache: 'force-cache' })
    .then(response => {
      if (!response.ok) throw new Error('Audio unavailable');
      return response.blob();
    }).then(blob => {
      if (signal.aborted || player !== owner) return;
      const url = URL.createObjectURL(blob);
      audioObjectUrls.add(url);
      chunk.audio = url;
    }).catch(() => {
      // Playback retains its original URL and normal retry path on failure.
      preparedAudio.delete(chunk);
    });
  preparedAudio.set(chunk, task);
}

function turn(direction, { clearPending = false } = {}) {
  if (!player) return;
  if (direction > 0) {
    if (player.error) {
      player.retry();
      return;
    }
    player.forward();
    prepareAudio(player.nextSequence);
    prepareAudio(player.nextSequence + 1);
  }
  else player.backward({ clearPending });
}

stage.addEventListener('wheel', (event) => {
  if (!player || event.ctrlKey) return;
  event.preventDefault();
  if (!startedByUser) {
    wheelAcc = 0;
    return;
  }
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? stage.clientHeight : 1;
  const delta = -event.deltaY * unit;
  if (Math.sign(delta) !== Math.sign(wheelAcc)) wheelAcc = 0;
  wheelAcc += delta;
  if (player.error && wheelAcc >= 120) {
    // Consume the whole recovery gesture instead of also creating reservations.
    wheelAcc = 0;
    turn(1);
    return;
  }
  while (Math.abs(wheelAcc) >= 120) {
    const direction = Math.sign(wheelAcc);
    wheelAcc -= direction * 120;
    turn(direction, { clearPending: true });
  }
}, { passive: false });
stage.addEventListener('click', (event) => {
  if (!player || !startedByUser && !event.isTrusted) return;
  startedByUser = true;
  turn(1);
});
stage.addEventListener('keydown', (event) => {
  if (['ArrowDown', 'PageDown', 'Enter'].includes(event.key)) {
    event.preventDefault();
    if (!player || !startedByUser && !event.isTrusted) return;
    startedByUser = true;
    turn(1);
  } else if (['ArrowUp', 'PageUp'].includes(event.key)) {
    event.preventDefault(); turn(-1);
  } else if (event.code === 'Space') {
    event.preventDefault(); player?.togglePause();
  }
});
$('restartBtn').addEventListener('click', () => {
  wheelAcc = 0;
  player?.restart();
});
$('rate').addEventListener('input', () => {
  audio.playbackRate = Number($('rate').value);
  audio.defaultPlaybackRate = audio.playbackRate;
  $('rateOut').textContent = `${audio.playbackRate.toFixed(2).replace(/0$/, '')}×`;
});
$('reloadBtn').addEventListener('click', () => initialize($('sutraSelect').value));
$('sutraSelect').addEventListener('change', () => initialize($('sutraSelect').value));

async function initialize(id = 'hannya') {
  const definition = sutras[id];
  if (!definition) return;
  const version = ++loadVersion;
  loadController?.abort();
  const controller = new AbortController();
  loadController = controller;
  const timeout = setTimeout(() => controller.abort(), 15000);
  player?.stopAudio();
  for (const url of audioObjectUrls) URL.revokeObjectURL(url);
  audioObjectUrls.clear();
  preparedAudio.clear();
  player = undefined;
  if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
  scrollFrame = null;
  audioStalled = false;
  dial.style.removeProperty('transform');
  characterTimings = []; characterOffsets = []; characterEntries = [];
  highlighted = drumFaceCenter = drumFaceCharacter = displayedSequence = displayedCharacter = null;
  drumPosition = activeCharacter = -1;
  wheelAcc = 0;
  dial.replaceChildren();
  buildDrum();
  $('textBlock').replaceChildren();
  $('textBlock').scrollTop = 0;
  $('textBlock').setAttribute('aria-label', definition.title + 'の全文');
  $('sutraName').textContent = definition.title;
  $('currentLine').textContent = '経文を読み込んでいます…';
  $('currentLine').classList.add('is-waiting');
  $('currentReading').textContent = $('currentTranslation').textContent = '';
  $('translationBlock').hidden = true;
  $('voiceBanner').hidden = $('reloadBtn').hidden = true;
  $('restartBtn').disabled = true;
  $('counter').textContent = $('rounds').textContent = $('queueCount').textContent = '0';
  $('progressLabel').textContent = $('drumPosition').textContent = '—';
  $('progressFill').style.width = '0%';
  $('drumSelection').textContent = '読み上げに合わせて、経文が一文字ずつ流れます。';
  $('statusText').textContent = '経文を読み込んでいます…';
  $('statusDot').className = 'dot busy';
  stage.setAttribute('aria-disabled', 'true');
  stage.dataset.state = 'loading';
  dial.dataset.moving = 'false';
  try {
    const [response, timingResponse] = await Promise.all([
      fetch(definition.source, { signal: controller.signal }),
      fetch(definition.timing, { cache: 'no-store', signal: controller.signal }),
    ]);
    if (!response.ok || !timingResponse.ok) throw new Error('Sutra unavailable');
    const [sutraText, timings] = await Promise.all([response.text(), timingResponse.json()]);
    const sutra = JSON.parse(sutraText);
    if (!Array.isArray(sutra.chunks) || !sutra.chunks.length
        || sutra.chunks.some(c => typeof c.text !== 'string' || typeof c.reading !== 'string')) throw new Error('Invalid sutra');
    if (sutra.chunks.some(c => typeof (c.translation ?? modernTranslations.get(c.text)) !== 'string'
        || !(c.translation ?? modernTranslations.get(c.text)).trim())) throw new Error('Missing modern translation');
    if (sutra.audioDirectory !== definition.audioDirectory) throw new Error('Invalid audio directory');
    const chunks = sutra.chunks.map((chunk, i) => ({ ...chunk,
      translation: chunk.translation ?? modernTranslations.get(chunk.text),
      audio: `${sutra.audioDirectory}/${String(i + 1).padStart(2, '0')}.wav`,
    }));
    const sutraDigest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(sutraText)))].map(b => b.toString(16).padStart(2, '0')).join('');
    if (timings.sutraSha256 !== sutraDigest) throw new Error('Character timing source mismatch');
    if (timings.version !== 1 || timings.sections.length !== chunks.length) throw new Error('Invalid character timing');
    const nextEntries = [], nextOffsets = [];
    for (const [section, timing] of timings.sections.entries()) {
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
      nextOffsets.push(nextEntries.length);
      timing.characters.forEach((cue, index) => nextEntries.push({ ...cue, section, index }));
      nextEntries.push({ text: '', reading: '', section, index: -1 });
    }
    if (version !== loadVersion) return;
    document.querySelector('.translation-label').textContent = sutra.translationLabel || '現代語訳（意訳）';
    characterTimings = timings.sections;
    characterOffsets = nextOffsets;
    characterEntries = nextEntries;
    for (const chunk of chunks) {
      const span = document.createElement('span');
      span.className = 'chunk';
      span.textContent = chunk.text + '　';
      $('textBlock').appendChild(span);
    }
    player = new SutraPlayer(chunks, audio, updateUI);
    stage.setAttribute('aria-disabled', 'false');
    $('restartBtn').disabled = false;
    updateUI();
  } catch {
    if (version !== loadVersion) return;
    stage.dataset.state = 'error';
    $('voiceBanner').hidden = false;
    $('voiceBanner').textContent = '経文を読み込めませんでした。接続を確認して経文を再読み込みしてください。';
    $('reloadBtn').hidden = false;
    $('statusText').textContent = '読み込みに失敗しました。';
    $('statusDot').className = 'dot warn';
  } finally {
    clearTimeout(timeout);
  }
}

initialize();
