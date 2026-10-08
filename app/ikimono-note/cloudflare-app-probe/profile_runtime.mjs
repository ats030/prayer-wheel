// Local inspector samples; never interpret these as production CPU accounting.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {request as httpRequest} from 'node:http';

const origin = 'http://127.0.0.1:8793';
const requestsPerCapture = 20;
const timedFetch = (url, options = {}) => fetch(url, {...options, signal: AbortSignal.timeout(10000)});
const {ws: WebSocket} = createRequire(import.meta.url)('../../dekita/node_modules/playwright-core/lib/utilsBundle.js');
const digest = execFileSync('python3', ['-c', 'import json; from build import bundle_digest,HERE; print(bundle_digest(json.loads((HERE/"manifest.json").read_text())))'],
  {cwd: new URL('.', import.meta.url), encoding: 'utf8'}).trim();
const health = await timedFetch(origin + '/health');
assert.equal(health.status, 200);
assert.equal(health.headers.get('X-Probe-Synthetic-AI'), '1');
assert.equal(health.headers.get('X-Probe-Profile-IO'), '1');
assert.equal(health.headers.get('X-Probe-Bundle-SHA256'), digest, 'Stale running bundle');
await health.arrayBuffer();
const targets = await timedFetch('http://127.0.0.1:9229/json').then(r => r.json());
assert.equal(targets.length, 1, 'Run only this local Worker');
const socket = new WebSocket(targets[0].webSocketDebuggerUrl, {origin: 'http://localhost:9229'});
await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
let serial = 0;
const pending = new Map();
socket.on('message', raw => {
  const message = JSON.parse(raw), waiter = pending.get(message.id);
  if (!waiter) return;
  pending.delete(message.id); clearTimeout(waiter.timer);
  message.error ? waiter.reject(new Error(JSON.stringify(message.error))) : waiter.resolve(message.result);
});
function command(method, params = {}) {
  const id = ++serial;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Inspector timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id, method, params}));
  });
}
const cases = [
  ['native', '/probe/profile/native-health'],
  ['minimal-asgi', '/probe/profile/asgi-health'],
  ['fastapi-async', '/probe/profile/fastapi-async-health'],
  ['fastapi-sync', '/probe/profile/fastapi-sync-health'],
  ['router-health', '/probe/profile/router-health'],
  ['full-health', '/probe/profile/full-health'],
  ['router-me', '/probe/profile/router-me'],
  ['full-me', '/probe/profile/full-me'],
];
const expectedMe = await timedFetch(origin + '/api/me').then(r => {
  assert.equal(r.status, 200); return r.json();
});
async function checked(name, path) {
  const response = await timedFetch(origin + path);
  assert.equal(response.status, 200, name);
  const body = await response.json();
  assert.deepEqual(body, name.endsWith('-me') ? expectedMe : {ok: true}, name);
  return body;
}
function forgedHostStatus(path) {
  // Fetch can replace the Host header; use the HTTP transport for this check.
  return new Promise((resolve, reject) => {
    const request = httpRequest(origin + path, {headers: {Host: 'example.invalid'}}, response => {
      response.resume(); response.on('end', () => resolve(response.statusCode));
      response.on('error', reject);
    });
    request.setTimeout(10000, () => request.destroy(new Error('Host check timeout')));
    request.on('error', reject); request.end();
  });
}
function summarize(profile) {
  const frames = new Map(profile.nodes.map(n => [n.id, n.callFrame.functionName]));
  const totals = new Map();
  let active = 0, idle = 0;
  assert.equal(profile.samples.length, profile.timeDeltas.length);
  for (let i = 0; i < profile.samples.length; i++) {
    const name = frames.get(profile.samples[i]), delta = profile.timeDeltas[i] / 1000;
    assert.ok(Number.isFinite(delta) && delta >= 0);
    if (name === '(idle)' || name === '(root)') idle += delta;
    else { active += delta; totals.set(name, (totals.get(name) ?? 0) + delta); }
  }
  assert.ok(profile.samples.length > 0, 'No profiler samples');
  return {active_sampled_ms: +active.toFixed(3), idle_sampled_ms: +idle.toFixed(3), samples: profile.samples.length,
    top_frames: [...totals].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([name, ms]) => ({name, ms: +ms.toFixed(3)}))};
}
try {
  // Require every added route to enforce method and localhost restrictions.
  for (const [, path] of cases.filter(([, p]) => p.startsWith('/probe/'))) {
    assert.equal((await timedFetch(origin + path, {method: 'POST'})).status, 404, 'Diagnostic POST accepted');
    assert.equal(await forgedHostStatus(path), 403, 'Nonlocal diagnostic accepted');
  }
  for (const [name, path] of cases) await checked(name, path);
  await command('Profiler.enable');
  await command('Profiler.setSamplingInterval', {interval: 1000});
  // Interleave cases and reverse order on alternate rounds to reduce order bias.
  for (let round = 0; round < 5; round++) {
    const ordered = round % 2 ? [...cases].reverse() : cases;
    for (const [name, path] of ordered) {
      await command('Profiler.start');
      const start = performance.now();
      try {
        for (let request = 0; request < requestsPerCapture; request++) await checked(name, path);
      }
      catch (error) { await command('Profiler.stop'); throw error; }
      const wall = performance.now() - start;
      const {profile} = await command('Profiler.stop');
      const summary = summarize(profile);
      console.log(JSON.stringify({name, round, scope: 'local V8 samples, not production CPU',
        bundle_sha256: digest, requests: requestsPerCapture,
        wall_ms: +wall.toFixed(3), wall_per_request_ms: +(wall / requestsPerCapture).toFixed(3),
        active_per_request_ms: +(summary.active_sampled_ms / requestsPerCapture).toFixed(3), ...summary}));
    }
  }
} finally {
  socket.terminate();
  for (const waiter of pending.values()) clearTimeout(waiter.timer);
}
