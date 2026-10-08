// Local V8 sampling only: these numbers are not Cloudflare production CPU accounting.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';

// Reuse Playwright's installed ws implementation to supply Wrangler's required Origin.
const {ws: WebSocket} = createRequire(import.meta.url)('../../dekita/node_modules/playwright-core/lib/utilsBundle.js');

const targets = await fetch('http://127.0.0.1:9229/json').then(response => response.json());
assert.equal(targets.length, 1, 'Start only this probe on the default inspector port');
const socket = new WebSocket(targets[0].webSocketDebuggerUrl, {origin: 'http://localhost:9229'});
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, {once: true});
  socket.addEventListener('error', reject, {once: true});
});
let serial = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  const waiter = pending.get(message.id);
  if (!waiter) return;
  pending.delete(message.id);
  clearTimeout(waiter.timer);
  if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
  else waiter.resolve(message.result);
});
function command(method, params = {}) {
  const id = ++serial;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Inspector timeout: ${method}`));
    }, 20000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params}));
  });
}
function summarize(profile) {
  const names = new Map(profile.nodes.map(node => [node.id, node.callFrame.functionName]));
  let active = 0;
  let idle = 0;
  for (let index = 0; index < profile.samples.length; index++) {
    const name = names.get(profile.samples[index]);
    const delta = profile.timeDeltas[index] / 1000;
    if (name === '(idle)' || name === '(root)') idle += delta;
    else active += delta;
  }
  return {active_sampled_ms: Number(active.toFixed(3)),
          idle_sampled_ms: Number(idle.toFixed(3)), samples: profile.samples.length};
}
try {
  await command('Profiler.enable');
  await command('Profiler.setSamplingInterval', {interval: 1000});
  const raw = await readFile(new URL('./fixtures/sharp.jpg', import.meta.url));
  // Warm the interpreter and code paths before profiling.
  await fetch('http://127.0.0.1:8790/measure', {method: 'POST', body: raw}).then(response => response.json());
  for (let repetition = 0; repetition < 3; repetition++) {
    await command('Profiler.start');
    const response = await fetch('http://127.0.0.1:8790/measure', {method: 'POST', body: raw});
    assert.equal(response.status, 200);
    const result = await response.json();
    const {profile} = await command('Profiler.stop');
    assert.equal(result.ok, true);
    const summary = summarize(profile);
    assert.ok(summary.samples > 0);
    console.log(JSON.stringify({repetition, scope: 'local V8 sampling, not production CPU',
      ...summary, quality_wall_ms: result.quality_wall_ms, prepare_wall_ms: result.prepare_wall_ms}));
  }
} finally {
  socket.terminate();
  for (const waiter of pending.values()) clearTimeout(waiter.timer);
}
