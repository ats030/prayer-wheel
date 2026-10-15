import test from 'node:test';
import assert from 'node:assert/strict';
import { SutraPlayer } from '../player.js';

class FakeAudio extends EventTarget {
  constructor() { super(); this.sources = []; this.promise = Promise.resolve(); }
  load() { if (this.src) this.sources.push(this.src); }
  play() { this.playCount = (this.playCount || 0) + 1; return this.promise; }
  pause() {}
  removeAttribute() { this.src = ''; }
  emit(type) { this.dispatchEvent(new Event(type)); }
}
function setup(t, count = 3) {
  const audio = new FakeAudio();
  const p = new SutraPlayer(Array.from({ length: count }, (_, i) => ({ audio: `${i}.wav` })), audio);
  t.after(() => p.restart());
  return { p, audio };
}

test('wheel response is immediate; highlight waits for actual playback; five waiting sections', (t) => {
  const { p, audio } = setup(t);
  p.forward();
  assert.equal(p.angle, 30);
  assert.equal(p.currentSequence, -1);
  audio.emit('playing');
  for (let i = 0; i < 5; i++) assert.equal(p.forward(), true);
  assert.equal(p.pending.length, 5);
  assert.equal(p.currentSequence, 0);
  assert.equal(p.forward(), false);
  assert.equal(p.angle, 180);
  assert.equal(p.nextSequence, 6);
});

test('reverse removes only the last reservation, preserves active audio and reuses its position', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); p.forward(); p.forward();
  const active = p.active;
  p.backward();
  assert.equal(p.active, active);
  assert.equal(p.currentSequence, 0);
  assert.equal(p.nextSequence, 2);
  p.forward();
  assert.deepEqual(p.pending.map(e => e.sequence), [1, 2]);
});

test('reverse without reservations replays previous section; beginning is bounded', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('ended');
  assert.equal(p.backward(), false);
  p.forward(); audio.emit('playing');
  assert.equal(p.backward(), true);
  assert.equal(p.active.sequence, 0);
  assert.equal(p.nextSequence, 1);
  audio.emit('playing'); audio.emit('ended'); p.forward();
  assert.equal(p.active.sequence, 1);
});

test('immediate reverse discards every reservation and replays the previous section', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('ended');
  p.forward(); audio.emit('playing');
  p.forward(); p.forward(); p.forward();
  assert.equal(p.backward({ clearPending: true }), true);
  assert.deepEqual(p.pending, []);
  assert.equal(p.active.sequence, 0);
  assert.equal(p.nextSequence, 1);
  assert.equal(p.turns, 1);
  assert.equal(p.angle, 30);
  audio.emit('playing'); audio.emit('ended'); p.forward();
  assert.equal(p.active.sequence, 1);
});

test('immediate reverse at the beginning clears reservations without wrapping', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); p.forward(); p.forward();
  const active = p.active;
  assert.equal(p.backward({ clearPending: true }), false);
  assert.equal(p.active, active);
  assert.deepEqual(p.pending, []);
  assert.equal(p.nextSequence, 1);
  assert.equal(p.turns, 1);
  audio.emit('ended'); p.forward();
  assert.equal(p.active.sequence, 1);
});

test('immediate reverse preserves pause and resumes from the previous source', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('ended');
  p.forward(); audio.emit('playing'); p.forward(); p.togglePause();
  const loads = audio.sources.length;
  p.backward({ clearPending: true });
  assert.equal(p.paused, true);
  assert.equal(p.active.sequence, 0);
  assert.equal(p.pending.length, 0);
  assert.equal(audio.sources.length, loads);
  p.togglePause();
  assert.equal(audio.src, '0.wav');
  audio.emit('playing');
  assert.equal(p.currentSequence, 0);
});

test('immediate reverse recovers a failed section and retains cycle accounting', (t) => {
  const { p, audio } = setup(t);
  for (let i = 0; i < 3; i++) { p.forward(); audio.emit('playing'); audio.emit('ended'); }
  p.forward(); p.forward(); audio.emit('error');
  p.backward({ clearPending: true });
  assert.equal(p.error, '');
  assert.equal(p.active.sequence, 2);
  assert.equal(p.nextSequence, 3);
  assert.deepEqual(p.pending, []);
  assert.equal(p.completedCycles.size, 1);
  audio.emit('playing'); audio.emit('ended');
  assert.equal(p.completedCycles.size, 1);
});

test('cycles count only on successful final playback and do not duplicate on rewind', (t) => {
  const { p, audio } = setup(t);
  for (let i = 0; i < 3; i++) { p.forward(); audio.emit('playing'); audio.emit('ended'); }
  assert.equal(p.completedCycles.size, 1);
  p.backward(); audio.emit('playing'); audio.emit('ended');
  p.forward(); audio.emit('playing'); audio.emit('ended');
  assert.equal(p.completedCycles.size, 1);
  p.forward(); audio.emit('playing');
  assert.equal(p.active.sequence, 3);
  assert.equal(p.currentSequence % 3, 0);
  audio.emit('ended');
  for (let i = 0; i < 2; i++) { p.forward(); audio.emit('playing'); audio.emit('ended'); }
  assert.equal(p.completedCycles.size, 2);
});

test('pause preserves reservations and resume does not reload the current section', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); p.forward(); p.togglePause();
  audio.emit('ended');
  assert.equal(p.currentSequence, 0);
  assert.equal(p.pending.length, 1);
  p.forward();
  assert.equal(p.paused, true);
  const count = audio.sources.length;
  p.togglePause();
  assert.equal(audio.sources.length, count);
  audio.emit('playing'); audio.emit('ended');
  assert.equal(p.active.sequence, 1);
});

test('failure does not complete or discard a section; retry keeps order and wheel position', (t) => {
  const { p, audio } = setup(t);
  p.forward(); p.forward(); audio.emit('error'); audio.emit('ended');
  assert.ok(p.error);
  assert.equal(p.currentSequence, -1);
  assert.equal(p.active.sequence, 0);
  assert.equal(p.forward(), false);
  const angle = p.angle;
  p.retry(); audio.emit('playing'); audio.emit('ended');
  assert.equal(p.angle, angle);
  assert.equal(p.active.sequence, 1);
  assert.equal(p.error, '');
});

test('late play rejection after reset cannot corrupt a fresh session', async (t) => {
  const { p, audio } = setup(t);
  let reject;
  audio.promise = new Promise((_, r) => { reject = r; });
  p.forward(); p.forward(); p.restart();
  audio.promise = Promise.resolve(); p.forward();
  reject(new Error('old playback canceled'));
  await Promise.resolve();
  assert.equal(p.error, '');
  assert.equal(p.active.sequence, 0);
  assert.equal(p.pending.length, 0);
  assert.equal(p.turns, 1);
});

test('pause during loading invalidates rejection; resume can retry playback', async (t) => {
  const { p, audio } = setup(t);
  let reject;
  audio.promise = new Promise((_, r) => { reject = r; });
  p.forward(); p.togglePause();
  reject(new Error('aborted by pause'));
  await Promise.resolve();
  assert.equal(p.error, '');
  audio.promise = Promise.resolve(); p.togglePause(); audio.emit('playing');
  assert.equal(p.currentSequence, 0);
});

test('autoplay denial keeps section for a user initiated retry', async (t) => {
  const { p, audio } = setup(t);
  audio.promise = Promise.reject(Object.assign(new Error('gesture required'), { name: 'NotAllowedError' }));
  p.forward();
  await Promise.resolve();
  assert.match(p.error, /操作/);
  assert.equal(p.active.sequence, 0);
  audio.promise = Promise.resolve(); p.retry(); audio.emit('playing');
  assert.equal(p.currentSequence, 0);
  assert.equal(p.turns, 1);
});

test('pause without any playback does nothing', (t) => {
  const { p } = setup(t);
  p.togglePause();
  assert.equal(p.paused, false);
});

test('reverse without a reservation preserves pause and defers previous playback', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('ended');
  p.forward(); audio.emit('playing'); p.togglePause();
  const plays = audio.playCount;
  p.backward();
  assert.equal(p.paused, true);
  assert.equal(p.active.sequence, 0);
  assert.equal(p.pending.length, 0);
  assert.equal(audio.playCount, plays);
  p.togglePause(); audio.emit('playing');
  assert.equal(p.active.sequence, 0);
  assert.equal(p.currentSequence, 0);
});

test('retry shows loading until playback actually restarts', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('error'); p.retry();
  assert.equal(p.active.started, false);
  audio.emit('playing');
  assert.equal(p.active.started, true);
});

test('repeated paused backward moves the held section without creating a cancelable reservation', (t) => {
  const { p, audio } = setup(t, 5);
  for (let i = 0; i < 3; i++) { p.forward(); audio.emit('playing'); audio.emit('ended'); }
  p.forward(); audio.emit('playing'); p.togglePause();
  const plays = audio.playCount;
  p.backward(); p.backward();
  assert.equal(p.active.sequence, 1);
  assert.equal(p.nextSequence, 2);
  assert.equal(p.pending.length, 0);
  assert.equal(audio.playCount, plays);
  p.backward();
  assert.equal(p.active.sequence, 0);
  assert.equal(p.backward(), false);
  p.togglePause();
  assert.equal(audio.src, '0.wav');
  audio.emit('playing');
  assert.equal(p.currentSequence, 0);
});

test('progress after a stalled event cancels timeout while audio is advancing', (t) => {
  const { p, audio } = setup(t);
  p.forward(); audio.emit('playing'); audio.emit('stalled');
  assert.ok(p.timer);
  audio.currentTime = 1; audio.paused = false; audio.emit('timeupdate');
  assert.equal(p.timer, null);
});
