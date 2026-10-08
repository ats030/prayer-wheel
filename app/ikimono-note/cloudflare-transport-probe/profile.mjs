// All photos, keys and provider responses are synthetic. No external AI calls.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {request as httpRequest} from 'node:http';
const fetch = (url, options = {}) => globalThis.fetch(url, {...options, signal: AbortSignal.timeout(15000)});
const origin = 'http://127.0.0.1:8794', pythonOrigin = 'http://127.0.0.1:8793';
const pythonHealth = await fetch(pythonOrigin + '/health');
assert.equal(pythonHealth.headers.get('X-Probe-Profile-IO'), '1');
assert.equal(pythonHealth.headers.get('X-Probe-Synthetic-AI'), '1');
const pythonDigest = execFileSync('python3', ['-c', 'import json; from build import bundle_digest,HERE; print(bundle_digest(json.loads((HERE/"manifest.json").read_text())))'],
  {cwd: new URL('../cloudflare-app-probe/', import.meta.url), encoding: 'utf8'}).trim();
assert.equal(pythonHealth.headers.get('X-Probe-Bundle-SHA256'), pythonDigest, 'Stale Python template source');
const workerDigest = createHash('sha256').update(await readFile(new URL('./worker.mjs', import.meta.url))).digest('hex');
const health = await fetch(origin + '/health').then(r => r.json());
assert.equal(health.synthetic, true); assert.equal(health.source_sha256, workerDigest, 'Stale JS Worker');
const templateResult = await fetch(pythonOrigin + '/probe/profile/gemini-template').then(r => r.json());
assert.equal(templateResult.network_calls, 0);
const template = templateResult.template;
const photo = await readFile(new URL('../cloudflare-app-probe/profile-fixtures/noise.jpg', import.meta.url));
const hash = createHash('sha256').update(photo).digest('hex');
function form(count, value = template) {
  const result = new FormData();
  result.append('template', JSON.stringify(value));
  for (let i = 0; i < count; i++) result.append('files', new Blob([photo], {type: 'image/jpeg'}), 'synthetic.jpg');
  return result;
}
async function request(path, body) { return fetch(origin + path, {method: 'POST', body}); }
for (const count of [1, 3]) {
  const response = await request('/payload-checked', form(count)); assert.equal(response.status, 200);
  const result = await response.json();
  const expected = structuredClone(template);
  expected.contents[0].parts = [...Array.from({length: count}, () => ({inline_data: {mime_type: 'image/jpeg', data: photo.toString('base64')}})), template.contents[0].parts[1]];
  assert.deepEqual(result.payload, expected, 'Model prompt/config/photo mismatch');
  assert.deepEqual(result.probe.sha256, Array(count).fill(hash)); assert.equal(result.network_calls, 0);
  const wire = Buffer.from(JSON.stringify(expected));
  assert.equal(result.wire_bytes, wire.length); assert.equal(result.wire_sha256, createHash('sha256').update(wire).digest('hex'));
  const stream = await fetch(origin + '/wire', {method: 'POST', body: wire, headers: {'Content-Type': 'application/json'}});
  assert.equal(stream.status, 200); assert.deepEqual(Buffer.from(await stream.arrayBuffer()), wire);
}
assert.equal((await request('/payload', form(4))).status, 400);
assert.equal((await request('/payload', form(1, {}))).status, 400);
assert.equal((await fetch(origin + '/payload')).status, 405);
assert.equal((await fetch(origin + '/unknown')).status, 404);
assert.equal((await fetch(origin + '/wire')).status, 405);
assert.equal((await fetch(origin + '/wire', {method: 'POST', body: 'wrong-type'})).status, 415);
// Node fetch ignores a Host override; use raw HTTP for this boundary check.
const rejectedHost = await new Promise((resolve, reject) => {
  const req = httpRequest(origin + '/health', {headers: {Host: 'attacker.invalid'}}, response => {
    response.resume(); response.on('end', () => resolve(response.statusCode));
  });
  req.on('error', reject); req.setTimeout(15000, () => req.destroy(new Error('Host check timed out'))); req.end();
});
assert.equal(rejectedHost, 403);
const {ws: WebSocket} = createRequire(import.meta.url)('../../dekita/node_modules/playwright-core/lib/utilsBundle.js');
const targets = await fetch('http://127.0.0.1:9230/json').then(r => r.json());
assert.equal(targets.length, 1);
const socket = new WebSocket(targets[0].webSocketDebuggerUrl, {origin: 'http://localhost:9230'});
await new Promise((resolve, reject) => {socket.once('open', resolve); socket.once('error', reject);});
let serial = 0; const pending = new Map();
socket.on('message', raw => { const message = JSON.parse(raw), waiter = pending.get(message.id); if (!waiter) return;
  pending.delete(message.id); clearTimeout(waiter.timer); message.error ? waiter.reject(new Error(JSON.stringify(message.error))) : waiter.resolve(message.result); });
function command(method, params = {}) { const id = ++serial; return new Promise((resolve, reject) => {
  const timer = setTimeout(() => {pending.delete(id); reject(new Error('Inspector timeout: ' + method));}, 20000);
  pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id, method, params})); }); }
function activeTime(profile) { const names = new Map(profile.nodes.map(n => [n.id, n.callFrame.functionName])); let active = 0;
  profile.samples.forEach((sample, i) => {if (!['(idle)', '(root)'].includes(names.get(sample))) active += profile.timeDeltas[i] / 1000;}); return Number(active.toFixed(3)); }
function hotSamples(profile) {
  const frames = new Map(profile.nodes.map(n => [n.id, n.callFrame])), times = new Map();
  profile.samples.forEach((sample, i) => {
    const frame = frames.get(sample), key = `${frame.functionName} @ ${frame.url}`;
    times.set(key, (times.get(key) || 0) + profile.timeDeltas[i] / 1000);
  });
  return [...times].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([frame, ms]) => ({frame, sampled_ms: Number(ms.toFixed(3))}));
}
let profilerActive = false;
try {
  await command('Profiler.enable'); await command('Profiler.setSamplingInterval', {interval: 1000});
  for (const count of [1, 3]) {
    const warm = await request('/payload', form(count)); assert.equal(warm.status, 200); await warm.arrayBuffer();
    for (let repetition = 0; repetition < 5; repetition++) {
      await command('Profiler.start'); profilerActive = true; const start = performance.now();
      const batchSize = 20;
      for (let item = 0; item < batchSize; item++) {
        const response = await request('/payload', form(count)); assert.equal(response.status, 200);
        const result = await response.json(); assert.deepEqual(result.probe.sha256, Array(count).fill(hash)); assert.equal(result.network_calls, 0);
      }
      const wall = performance.now() - start, {profile} = await command('Profiler.stop');
      profilerActive = false;
      console.log(JSON.stringify({name: `js-native-gemini-payload-${count}x-${photo.length}-bytes`, repetition,
        scope: 'local V8 samples, not production CPU', source_sha256: workerDigest, python_bundle_sha256: pythonDigest,
        status: 200, checked_requests: batchSize, photo_sha256: hash, network_calls: 0,
        active_sampled_ms: activeTime(profile), active_sampled_ms_per_request: Number((activeTime(profile) / batchSize).toFixed(3)),
        wall_ms: Number(wall.toFixed(3)), samples: profile.samples.length, hot_samples: hotSamples(profile)}));
    }
  }
  for (const count of [1, 3]) {
    const expected = structuredClone(template);
    expected.contents[0].parts = [...Array.from({length: count}, () => ({inline_data: {mime_type: 'image/jpeg', data: photo.toString('base64')}})), template.contents[0].parts[1]];
    const wire = Buffer.from(JSON.stringify(expected));
    for (let repetition = 0; repetition < 5; repetition++) {
      await command('Profiler.start'); profilerActive = true; const start = performance.now(), batchSize = 20;
      for (let item = 0; item < batchSize; item++) {
        const response = await fetch(origin + '/wire', {method: 'POST', body: wire, headers: {'Content-Type': 'application/json'}});
        assert.equal(response.status, 200); assert.equal(response.headers.get('X-Probe-Network-Calls'), '0');
        assert.deepEqual(Buffer.from(await response.arrayBuffer()), wire, 'Stream changed outgoing payload bytes');
      }
      const wall = performance.now() - start, {profile} = await command('Profiler.stop');
      profilerActive = false;
      console.log(JSON.stringify({name: `js-wire-forward-${count}x-${photo.length}-bytes`, repetition,
        scope: 'local V8 samples, not production CPU; forwarding only, no validation/auth/network',
        source_sha256: workerDigest, python_bundle_sha256: pythonDigest, status: 200, checked_requests: batchSize,
        photo_sha256: hash, wire_sha256: createHash('sha256').update(wire).digest('hex'), network_calls: 0,
        active_sampled_ms: activeTime(profile), active_sampled_ms_per_request: Number((activeTime(profile) / batchSize).toFixed(3)),
        wall_ms: Number(wall.toFixed(3)), samples: profile.samples.length, hot_samples: hotSamples(profile)}));
    }
  }
} finally {
  try { if (profilerActive) await command('Profiler.stop'); }
  finally { socket.close(); }
}
