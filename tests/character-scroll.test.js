import test from 'node:test';
import assert from 'node:assert/strict';
import { characterPosition } from '../character-scroll.js';

const cues = [{start: .02, end: .3}, {start: .3, end: .95}, {start: 1.05, end: 1.4}];
test('different readings travel the same row distance over their own duration', () => {
  assert.ok(Math.abs(characterPosition(cues, .16).position) < 1e-9);
  assert.ok(Math.abs(characterPosition(cues, .625).position - 1) < 1e-9);
  assert.deepEqual(characterPosition(cues, .01), {index: 0, position: -.5});
});
test('breaths and the end are bounded, and a retry or rewind is clock-derived', () => {
  assert.deepEqual(characterPosition(cues, 1), {index: 1, position: 1.5});
  assert.deepEqual(characterPosition(cues, 10), {index: 2, position: 2.5});
  assert.equal(characterPosition(cues, .02).position, -.5);
  assert.equal(characterPosition(cues, .3).position, .5);
});
test('every voiced interval centers its glyph at midpoint, and section boundaries meet', () => {
  for (let index = 0; index < cues.length; index++) {
    const cue = cues[index];
    assert.ok(Math.abs(characterPosition(cues, (cue.start + cue.end) / 2).position - index) < 1e-9);
    for (const fraction of [0, .25, .5, .75, 1]) {
      const time = cue.start + fraction * (cue.end - cue.start);
      assert.ok(Math.abs(characterPosition(cues, time).position - index) <= .500000001);
    }
  }
  assert.equal(characterPosition(cues, 10).position, cues.length + characterPosition(cues, 0).position);
});
test('reduced motion changes the character without interpolating rotation', () => {
  assert.deepEqual(characterPosition(cues, .625, true), {index: 1, position: 1});
});
