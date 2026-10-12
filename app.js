'use strict';

/* ================= Data ================= */

const HEART_SUTRA = [
  '観自在菩薩、行深般若波羅蜜多時、照見五蘊皆空、度一切苦厄。',
  '須菩提、色即是空、空即是色、色不異空、空不異色、色従空出、空従色出、受想行識亦復如是。',
  '須菩提、是諸法空相、不生不滅、不浄不垢、不増不減、是故空中無色、無受想行識、無眼耳鼻舌身意、無色聲香味触法、無眼界、乃至無意識界、無無明、亦無無明尽、乃至無老死、亦無老死尽、無苦集滅道、無智亦無得、以無所得故、菩提薩埵、依般若波羅蜜多故、心無罣礙、無罣礙故、無有恐怖、遠離顛倒夢想、究竟涅槃。',
  '三世諸仏、依般若波羅蜜多故、得阿耨多羅三藐三菩提。',
  '故知般若波羅蜜多、是大神咒、是大明呪、是無上呪、是無等呪、能除一切苦、真実不虚。',
  '故説般若波羅蜜多呪、即説呪曰、羯誅羯誅、摩訶羯誅、摩訶提羯誅、菩提薩婆訶。',
].join('');

const MAX_QUEUE = 5;
const WHEEL_STEP = 120;   // deltaY accumulated per turn
const TURN_DEG = 30;      // wheel rotation per turn (1 of 12 detents)

/* ================= State ================= */

const state = {
  sutraName: '心経',
  rawText: HEART_SUTRA,
  chunks: [],
  index: 0,        // next chunk to enqueue
  queued: 0,       // utterances in flight
  rotations: 0,
  rounds: 0,
  paused: false,
  session: 0,      // invalidates stale utterance callbacks
  angle: 0,
  hasVoice: false,
};

/* ================= DOM ================= */

const $ = (id) => document.getElementById(id);
const dialEl = $('dial');
const stageEl = $('stage');
const counterEl = $('counter');
const roundsEl = $('rounds');
const statusDot = $('statusDot');
const statusText = $('statusText');
const currentLineEl = $('currentLine');
const textBlockEl = $('textBlock');
const progressFill = $('progressFill');
const progressLabel = $('progressLabel');
const voiceSelect = $('voiceSelect');
const rateInput = $('rate');
const rateOut = $('rateOut');
const pauseBtn = $('pauseBtn');
const restartBtn = $('restartBtn');
const sutraBtn = $('sutraBtn');
const fileInput = $('file');
const voiceBanner = $('voiceBanner');

/* ================= Sutra chunking ================= */

function cleanText(text) {
  return text.replace(/\s+/g, '');
}

function splitChunks(text) {
  const clean = cleanText(text);
  if (!clean) return [];
  const parts = clean.split(/([、。；！？,!?;])/);
  const chunks = [];
  let buf = '';
  for (const part of parts) {
    if (!part) continue;
    buf += part;
    if (buf.length >= 15) {
      chunks.push(buf);
      buf = '';
    }
  }
  if (buf) {
    const last = chunks.length - 1;
    if (last >= 0 && chunks[last].length <= 18) chunks[last] += buf;
    else chunks.push(buf);
  }
  return chunks;
}

/* ================= Wheel visual ================= */

function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
}

function buildWheelDecor() {
  const NS = 'http://www.w3.org/2000/svg';
  const spokes = $('spokes');
  const petals = $('petals');
  for (let i = 0; i < 12; i++) {
    const [x1, y1] = polar(200, 200, 62, i * 30);
    const [x2, y2] = polar(200, 200, 146, i * 30);
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', x1); line.setAttribute('y1', y1);
    line.setAttribute('x2', x2); line.setAttribute('y2', y2);
    line.setAttribute('class', 'spoke');
    spokes.appendChild(line);

    const [px, py] = polar(200, 200, 104, i * 30 + 15);
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('cx', px); dot.setAttribute('cy', py);
    dot.setAttribute('r', 3);
    dot.setAttribute('class', 'petal');
    petals.appendChild(dot);
  }
}

function spin(dial, deg) {
  state.angle += deg;
  dial.style.transform = 'rotate(' + state.angle + 'deg)';
}

function setRimText(text) {
  const clean = cleanText(text);
  const rim = clean.length <= 60 ? clean : clean.slice(0, 60);
  $('rimTextPath').textContent = rim;
}

/* ================= Voices ================= */

let voices = [];

function applyVoiceChoice(name) {
  state.voice = voices.find((v) => v.name === name) || null;
  state.hasVoice = voices.some((v) => v.lang.toLowerCase().startsWith('ja'));
  voiceBanner.hidden = state.hasVoice;
}

function loadVoices() {
  voices = ('speechSynthesis' in window) ? speechSynthesis.getVoices() : [];
  voiceSelect.innerHTML = '';
  if (!voices.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'システム既定';
    voiceSelect.appendChild(opt);
    voiceSelect.disabled = true;
    state.voice = null;
    state.hasVoice = false;
    voiceBanner.hidden = false;
    return;
  }
  voiceSelect.disabled = false;
  const preferred = voices
    .filter((v) => v.lang.toLowerCase().startsWith('ja'))
    .sort((a, b) => (a.lang === 'ja-JP' ? -1 : 1) - (b.lang === 'ja-JP' ? -1 : 1));
  for (const v of voices) {
    const opt = document.createElement('option');
    opt.value = v.name;
    opt.textContent = v.name + ' [' + v.lang + ']';
    voiceSelect.appendChild(opt);
  }
  const def = preferred[0] || voices[0];
  voiceSelect.value = def.name;
  state.voice = def;
  state.hasVoice = preferred.length > 0;
  voiceBanner.hidden = state.hasVoice;
}

if ('speechSynthesis' in window) {
  speechSynthesis.onvoiceschanged = loadVoices;
}
loadVoices();

/* ================= Speech ================= */

function canSpeak() { return 'speechSynthesis' in window; }

function speakChunk(i, label) {
  const sess = state.session;
  const text = state.chunks[i];
  if (!canSpeak()) {
    // No TTS support: advance the flow visually only.
    state.queued += 1;
    onChunkStarted(i, sess, label);
    window.setTimeout(() => onChunkFinished(sess, label), 400);
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  if (state.voice) {
    u.voice = state.voice;
    u.lang = state.voice.lang;
  } else {
    u.lang = 'ja-JP';
  }
  u.rate = parseFloat(rateInput.value);
  onChunkStarted(i, sess); // mark current line at enqueue time (onstart also refreshes)
  u.onstart = () => {
    if (sess !== state.session) return;
    onChunkStarted(i, sess, label);
  };
  u.onend = () => {
    if (sess !== state.session) return;
    onChunkFinished(sess, label);
  };
  u.onerror = (e) => {
    if (sess !== state.session) return;
    if (e && e.error === 'canceled') return;
    onChunkFinished(sess, label);
  };
  state.queued += 1;
  speechSynthesis.speak(u);
}

/* ================= Turn progression ================= */

function onChunkStarted(i, sess) {
  if (sess !== state.session) return;
  setCurrent(i);
  updateUI();
}

function onChunkFinished(sess) {
  if (sess !== state.session) return;
  state.queued = Math.max(0, state.queued - 1);
  updateUI();
}

function setSutraStateReset() {
  state.index = 0;
  state.rotations = 0;
  state.rounds = 0;
  state.paused = false;
  state.current = -1;
  pauseBtn.textContent = '一時停止';
  currentLineEl.textContent = '—';
  textBlockEl.querySelectorAll('.chunk').forEach((el) => el.classList.remove('active'));
}

function setSutra(text, name) {
  cancelSpeech();
  state.sutraName = name || 'カスタムお経';
  state.rawText = text;
  state.chunks = splitChunks(text);
  setSutraStateReset();
  setRimText(text);
  renderText();
  updateUI();
}

function restart() {
  cancelSpeech();
  setSutraStateReset();
  // snap the wheel back to 0 without animation
  state.angle = 0;
  dialEl.style.transition = 'none';
  dialEl.style.transform = 'rotate(0deg)';
  void dialEl.getBoundingClientRect();
  dialEl.style.transition = '';
  updateUI();
}

function tryTurn(dir) {
  if (!state.chunks.length) {
    showNotice('お経のテキストがまだありません。', 'warn');
    return;
  }
  state.notice = null;
  if (dir > 0) {
    if (state.queued >= MAX_QUEUE) {
      showNotice('ごゆっくり — 朗読が追いついておりません', 'busy');
      return;
    }
    if (state.index >= state.chunks.length) {
      state.index = 0;
      state.rounds += 1;
    }
    const i = state.index;
    speakChunk(i, 'forward');
    state.index += 1;
  } else {
    if (state.index === 0) {
      showNotice('ここが最初の一節です。', 'idle');
      return;
    }
    if (state.queued > 0) cancelSpeech();
    state.paused = false;
    pauseBtn.textContent = '一時停止';
    if (canSpeak()) speechSynthesis.resume && speechSynthesis.resume();
    // index = number of lines already read; the last line read is index - 1.
    const prev = state.index - 1;
    state.index = prev;
    if (prev >= 1) {
      speakChunk(prev - 1, 'rewind');
    } else {
      // rewound past the first line: back to "nothing read yet"
      setCurrent(-1);
    }
  }
  state.rotations += 1;
  spin(dialEl, dir > 0 ? TURN_DEG : -TURN_DEG);
  updateUI();
}

function cancelSpeech() {
  state.session += 1; // invalidate in-flight callbacks
  state.queued = 0;
  if (canSpeak()) {
    try { speechSynthesis.cancel(); } catch (err) { /* ignore */ }
  }
}

function togglePause() {
  state.paused = !state.paused;
  if (canSpeak()) {
    try {
      if (state.paused) speechSynthesis.pause();
      else speechSynthesis.resume();
    } catch (err) { /* ignore */ }
  }
  pauseBtn.textContent = state.paused ? '再開' : '一時停止';
  updateUI();
}

/* ================= UI ================= */

function setCurrent(i) {
  state.current = i;
  currentLineEl.textContent = state.chunks[i] || '—';
  const spans = textBlockEl.querySelectorAll('.chunk');
  spans.forEach((el) => el.classList.toggle('active', Number(el.dataset.i) === i));
}

function renderText() {
  textBlockEl.innerHTML = '';
  const frag = document.createDocumentFragment();
  state.chunks.forEach((c, i) => {
    const span = document.createElement('span');
    span.className = 'chunk';
    span.dataset.i = String(i);
    span.textContent = c;
    frag.appendChild(span);
    frag.appendChild(document.createTextNode('\u3000'));
  });
  textBlockEl.appendChild(frag);
}

let noticeTimer = null;
function showNotice(text, mode) {
  state.notice = { text, mode };
  clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => { state.notice = null; updateUI(); }, 4000);
  updateUI();
}

function statusFromState() {
  if (state.notice) return state.notice;
  if (state.paused) return { text: '一時停止中。ホイールを回すと自動的に続きます。', mode: 'paused' };
  if (state.queued >= MAX_QUEUE) return { text: 'ごゆっくり — 朗読が追いついておりません', mode: 'busy' };
  if (state.queued > 0) return { text: '朗読中…', mode: 'speaking' };
  if (state.chunks.length && state.index >= state.chunks.length && state.rotations > 0) {
    return { text: '一週完了。続けて回ると新しい一週が始まります。', mode: 'idle' };
  }
  if (state.rotations === 0) return { text: '準備完了。ホイールを回してください。', mode: 'idle' };
  return { text: '準備完了', mode: 'idle' };
}

function updateUI() {
  counterEl.textContent = String(state.rotations);
  roundsEl.textContent = String(state.rounds);
  const n = state.chunks.length;
  const prog = n ? Math.min(state.index, n) / n : 0;
  progressFill.style.width = (prog * 100).toFixed(1) + '%';
  progressLabel.textContent = n ? Math.min(state.index, n) + ' / ' + n + ' 節目' : 'テキストなし';
  const s = statusFromState();
  statusText.textContent = s.text;
  statusDot.className = 'dot ' + s.mode;
  pauseBtn.disabled = false;
}

/* ================= Events ================= */

let wheelAcc = 0;
stageEl.addEventListener('wheel', (e) => {
  e.preventDefault();
  wheelAcc += e.deltaY;
  while (wheelAcc >= WHEEL_STEP) { wheelAcc -= WHEEL_STEP; tryTurn(1); }
  while (wheelAcc <= -WHEEL_STEP) { wheelAcc += WHEEL_STEP; tryTurn(-1); }
}, { passive: false, capture: true });

stageEl.addEventListener('click', () => tryTurn(1));

stageEl.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowDown' || e.key === 'PageDown') { e.preventDefault(); tryTurn(1); }
  else if (e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); tryTurn(-1); }
  else if (e.key === ' ') { e.preventDefault(); togglePause(); }
});

restartBtn.addEventListener('click', () => restart());
pauseBtn.addEventListener('click', () => togglePause());
sutraBtn.addEventListener('click', () => setSutra(HEART_SUTRA, '心経'));

fileInput.addEventListener('change', async () => {
  const f = fileInput.files && fileInput.files[0];
  fileInput.value = '';
  if (!f) return;
  try {
    const text = await f.text();
    if (!text.trim()) {
      showNotice('お経のテキストが空でした。', 'warn');
      return;
    }
    setSutra(text, f.name);
  } catch (err) {
    showNotice('ファイルの読み込みに失敗しました: ' + (err && err.message ? err.message : err), 'warn');
  }
});

voiceSelect.addEventListener('change', () => applyVoiceChoice(voiceSelect.value));

rateInput.addEventListener('input', () => {
  rateOut.textContent = fmtRate(parseFloat(rateInput.value));
});

function fmtRate(x) {
  return x.toFixed(2).replace(/0$/, '') + '×';
}

/* ================= Init ================= */

buildWheelDecor();
setSutra(HEART_SUTRA, '心経');
