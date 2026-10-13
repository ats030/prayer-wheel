import test from 'node:test';
import assert from 'node:assert/strict';
import { advanceMotion } from '../drum-motion.js';

test('a turn accelerates, then friction slows it without overshooting the face', () => {
  let state = { angle: -22.5, velocity: 0 };
  const samples = [];
  for (let i = 0; i < 120; i++) {
    state = advanceMotion(state, 0, 1 / 60);
    samples.push(state);
  }
  assert.ok(samples.every((s, i) => s.angle <= 0 && (i === 0 || s.angle > samples[i - 1].angle)));
  assert.ok(samples[7].velocity > samples[0].velocity);
  assert.ok(samples[30].velocity < samples[7].velocity);
  assert.ok(samples[16].angle < -5, 'still visibly moving after the old 280ms duration');
  assert.ok(Math.abs(state.angle) < .001 && state.velocity < .001);
});

test('timing stays consistent at different frame rates and after a suspended frame', () => {
  const initial = { angle: -22.5, velocity: 0 };
  const whole = advanceMotion(initial, 45, 1);
  for (const fps of [30, 60, 120]) {
    let state = initial;
    for (let i = 0; i < fps; i++) state = advanceMotion(state, 45, 1 / fps);
    assert.ok(Math.abs(state.angle - whole.angle) < 1e-9);
    assert.ok(Math.abs(state.velocity - whole.velocity) < 1e-9);
  }
  const resumed = advanceMotion(initial, 45, 30);
  assert.ok(Number.isFinite(resumed.angle) && Number.isFinite(resumed.velocity));
  assert.equal(resumed.angle, 45);
});

test('reversing keeps momentum initially, then friction brings the drum to the new face', () => {
  const running = advanceMotion({ angle: -22.5, velocity: 0 }, 45, .15);
  const reversing = advanceMotion(running, -22.5, .001);
  assert.ok(reversing.velocity > 0 && reversing.angle > running.angle);
  const stopped = advanceMotion(reversing, -22.5, 2);
  assert.ok(Math.abs(stopped.angle + 22.5) < .001 && Math.abs(stopped.velocity) < .01);
});
