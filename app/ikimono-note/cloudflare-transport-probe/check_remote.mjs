// Direct wrapper regression with synthetic inputs and no network or real secret.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import worker from './remote.mjs';
// Node 24 lacks the Workers runtime's native toBase64. This shim is only for
// wrapper correctness tests; CPU measurements always run in actual workerd.
if (!Uint8Array.prototype.toBase64) Object.defineProperty(Uint8Array.prototype, 'toBase64', {
  value() { return Buffer.from(this).toString('base64'); }
});
if (!Uint8Array.fromBase64) Uint8Array.fromBase64 = encoded => {
  const bytes = Buffer.from(encoded, 'base64');
  if (bytes.toString('base64') !== encoded) throw new TypeError('Invalid base64');
  return new Uint8Array(bytes);
};
const origin = 'https://ikimono-note-transport-preview.ats030.workers.dev';
const env = {IKIMONO_PREVIEW_PASSWORD: 'synthetic-wrapper-check'};
const auth = 'Basic ' + btoa('preview:' + env.IKIMONO_PREVIEW_PASSWORD);
const request = (path, headers = {}, method = 'GET', body) => new Request(origin + path, {method, body, headers});
assert.equal((await worker.fetch(request('/health'), env)).status, 401);
assert.equal((await worker.fetch(request('/session/in'), env)).status, 401);
assert.equal((await worker.fetch(request('/session/out', {Authorization: auth}), env)).status, 503);
const sessionEnv = {...env, IKIMONO_PROBE_SESSION_SECRET: 'synthetic-session-check'};
const out = await worker.fetch(request('/session/out', {Authorization: auth}), sessionEnv);
assert.equal(out.status, 200);
assert.deepEqual(await out.json(), {available: true, reason: '', signed_in: false, email: null});
assert.match(out.headers.get('X-Session-Source-SHA256'), /^[0-9a-f]{64}$/);
assert.equal((await worker.fetch(request('/session/out', {Authorization: auth}, 'POST', 'x'), sessionEnv)).status, 405);
assert.equal((await worker.fetch(request('/health', {Authorization: 'Basic invalid'}), env)).status, 401);
assert.equal((await worker.fetch(request('/health', {Authorization: auth}), {})).status, 503);
const unicodeEnv = {IKIMONO_PREVIEW_PASSWORD: '合成検証パスワード'};
const unicodeAuth = 'Basic ' + Buffer.from('preview:' + unicodeEnv.IKIMONO_PREVIEW_PASSWORD, 'utf8').toString('base64');
assert.equal((await worker.fetch(request('/health', {Authorization: unicodeAuth}), unicodeEnv)).status, 200);
assert.equal((await worker.fetch(new Request('https://attacker.invalid/health', {headers: {Authorization: auth}}), env)).status, 400);
assert.equal((await worker.fetch(request('/payload-checked', {Authorization: auth}), env)).status, 404);
const ordinary = await worker.fetch(request('/health', {Authorization: auth}), env);
assert.equal(ordinary.status, 200); assert.equal(ordinary.headers.get('Cache-Control'), 'no-store');
assert.equal(ordinary.headers.get('X-Preview-Isolate'), null); await ordinary.arrayBuffer();
const probe = await worker.fetch(request('/health', {Authorization: auth, 'X-Ikimono-CPU-Probe': '0123abcd'}), env);
assert.equal(probe.status, 200); assert.match(probe.headers.get('X-Preview-Isolate'), /^[0-9a-f-]{36}$/);
assert.ok(Number(probe.headers.get('X-Preview-Isolate-Invocation')) > 1);
assert.match(probe.headers.get('X-Transport-Source-SHA256'), /^[0-9a-f]{64}$/); await probe.arrayBuffer();
const denied = await worker.fetch(request('/health', {'X-Ikimono-CPU-Probe': '0123abcd'}), env);
assert.equal(denied.status, 401); assert.equal(denied.headers.get('X-Preview-Isolate'), null);
for (const count of [1, 3]) {
  const wire = await readFile(new URL(`./fixtures/wire-${count}.json`, import.meta.url));
  const binary = await readFile(new URL(`./fixtures/binary-${count}.bin`, import.meta.url));
  const binaryType = await readFile(new URL(`./fixtures/binary-${count}.type`, import.meta.url), 'utf8');
  const binaryHeaders = {Authorization: auth, 'Content-Type': binaryType, 'Content-Length': String(binary.length)};
  const composed = await worker.fetch(request(`/binary/${count}`, binaryHeaders, 'POST', binary), env);
  assert.equal(composed.status, 200);
  assert.equal(composed.headers.get('X-Probe-Network-Calls'), '0');
  assert.equal(composed.headers.get('X-Preview-Isolate'), null);
  assert.deepEqual(Buffer.from(await composed.arrayBuffer()), wire);
  assert.equal((await worker.fetch(request(`/binary/${count}`, {...binaryHeaders, Authorization: ''}, 'POST', binary), env)).status, 401);
  assert.equal((await worker.fetch(request(`/binary/${count === 1 ? 3 : 1}`, binaryHeaders, 'POST', binary), env)).status, 400);
  assert.equal((await worker.fetch(request(`/binary/${count}`, {Authorization: auth}), env)).status, 405);
  assert.equal((await worker.fetch(request(`/binary/${count}`, {...binaryHeaders, 'Content-Length': '99999999'}, 'POST', binary), env)).status, 400);
  const echo = await worker.fetch(request(`/wire/${count}`, {Authorization: auth, 'Content-Type': 'application/json',
    'Content-Length': String(wire.length)}, 'POST', wire), env);
  assert.equal(echo.status, 200); assert.deepEqual(Buffer.from(await echo.arrayBuffer()), wire);
  const checked = await worker.fetch(request(`/checked/${count}`, {Authorization: auth, 'Content-Type': 'application/json',
    'Content-Length': String(wire.length)}, 'POST', wire), env);
  assert.equal(checked.status, 200); assert.deepEqual(await checked.json(), {validated: true, photos: count, network_calls: 0});
  const altered = JSON.parse(wire); altered.generationConfig.temperature = 1;
  const invalid = Buffer.from(JSON.stringify(altered));
  assert.equal((await worker.fetch(request(`/checked/${count}`, {Authorization: auth, 'Content-Type': 'application/json',
    'Content-Length': String(invalid.length)}, 'POST', invalid), env)).status, 400);
  const form = await readFile(new URL(`./fixtures/multipart-${count}.bin`, import.meta.url));
  const type = await readFile(new URL(`./fixtures/multipart-${count}.type`, import.meta.url), 'utf8');
  assert.equal((await worker.fetch(request(`/binary/${count}`, {Authorization: auth, 'Content-Type': type,
    'Content-Length': String(form.length)}, 'POST', form), env)).status, 400);
  const payload = await worker.fetch(request(`/payload/${count}`, {Authorization: auth, 'Content-Type': type,
    'Content-Length': String(form.length)}, 'POST', form), env);
  assert.equal(payload.status, 200);
  const result = await payload.json(); assert.equal(result.network_calls, 0); assert.equal(result.probe.sha256.length, count);
}
console.log('PASS: protected wrapper auth/Host/no diagnostics/no ordinary IDs/byte streaming/1+3 synthetic payloads');
