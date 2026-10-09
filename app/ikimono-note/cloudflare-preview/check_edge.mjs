import assert from 'node:assert/strict';
import {createHmac} from 'node:crypto';
import worker from './edge.mjs';
import {securityHeaders, pythonBundleDigest} from './_edge_policy.mjs';
const origin = 'https://ikimono-note-preview.ats030.workers.dev';
let forwarded = [];
const env = {IKIMONO_PREVIEW_PASSWORD: 'synthetic-合成', IKIMONO_SESSION_SECRET: 'synthetic-session',
  IKIMONO_ALLOWED_HOSTS: 'ikimono-note-preview.ats030.workers.dev', IKIMONO_JS_SESSION: '1',
  IKIMONO_GOOGLE_CLIENT_ID: 'synthetic-id', IKIMONO_GOOGLE_CLIENT_SECRET: 'synthetic-key',
  IKIMONO_PUBLIC_ORIGIN: origin, DB: {}, PYTHON: {async fetch(request) {
    forwarded.push({url: request.url, method: request.method, headers: Object.fromEntries(request.headers), body: await request.text()});
    const headers = new Headers({Location: '/login', 'X-Preview-Isolate': 'backend-observation'});
    headers.append('Set-Cookie', 'first=one; HttpOnly'); headers.append('Set-Cookie', 'second=two; HttpOnly');
    return new Response('backend', {status: 303, headers});
  }}};
const credential = 'Basic ' + Buffer.from('preview:' + env.IKIMONO_PREVIEW_PASSWORD).toString('base64');
const request = (path, extra = {}, method = 'GET', body) => new Request(origin + path,
  {method, body, headers: {Authorization: credential, ...extra}});
const sign = payload => {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return body + '.' + createHmac('sha256', env.IKIMONO_SESSION_SECRET).update(body).digest('base64url');
};
const cookie = sign({sub: 'synthetic', email: '合成@example.invalid', exp: Date.now() / 1000 + 3600});
const expected = {available: true, reason: '', signed_in: true, email: '合成@example.invalid'};
assert.equal((await worker.fetch(new Request(origin + '/api/me'), env)).status, 401);
assert.equal((await worker.fetch(request('/api/me'), {...env, DB: null})).status, 503);
assert.equal((await worker.fetch(request('/api/me'), {...env, PYTHON: null})).status, 503);
assert.equal((await worker.fetch(request('/api/me'), {...env, IKIMONO_SESSION_SECRET: ''})).status, 503);
assert.equal((await worker.fetch(request('/api/me', {Host: 'attacker.invalid'}), env)).status, 400);
assert.equal((await worker.fetch(new Request('https://attacker.invalid/api/me', {headers: {Authorization: credential}}), env)).status, 400);
assert.equal((await worker.fetch(request('/probe/hidden'), env)).status, 404);
for (const value of [cookie, '"' + cookie + '"', 'invalid; ikimono_session=' + cookie]) {
  const response = await worker.fetch(request('/api/me', {Cookie: 'ikimono_session=' + value}), env);
  assert.deepEqual(await response.json(), expected);
  for (const [name, value] of Object.entries(securityHeaders)) assert.equal(response.headers.get(name), value);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('X-Preview-Isolate'), null);
}
for (const value of ['', cookie + 'x', sign({exp: 1}), cookie + '; ikimono_session=invalid']) {
  const response = await worker.fetch(request('/api/me', {Cookie: 'ikimono_session=' + value}), env);
  assert.deepEqual(await response.json(), {...expected, signed_in: false, email: null});
}
for (const name of ['IKIMONO_GOOGLE_CLIENT_ID', 'IKIMONO_GOOGLE_CLIENT_SECRET', 'IKIMONO_PUBLIC_ORIGIN']) {
  const response = await worker.fetch(request('/api/me'), {...env, [name]: ' '});
  assert.deepEqual(await response.json(), {available: false, reason: name + ' が未設定です', signed_in: false, email: null});
}
assert.equal((await (await worker.fetch(request('/api/me'), {...env, IKIMONO_PUBLIC_ORIGIN: '/'})).json()).available, false);
assert.equal((await worker.fetch(request('/api/me', {}, 'POST', 'x'), env)).status, 405);
assert.equal(forwarded.length, 0, 'Session API crossed Python boundary');
const result = await worker.fetch(request('/auth/google'), env);
assert.equal(result.status, 303); assert.equal(result.headers.get('Location'), '/login');
assert.deepEqual(result.headers.getSetCookie(), ['first=one; HttpOnly', 'second=two; HttpOnly']);
assert.equal(result.headers.get('X-Preview-Isolate'), null);
await worker.fetch(request('/identify', {'Content-Type': 'text/plain'}, 'POST', 'unchanged body'), env);
assert.deepEqual(forwarded.at(-1), {url: origin + '/identify', method: 'POST',
  headers: {authorization: credential, 'content-type': 'text/plain'}, body: 'unchanged body'});
await worker.fetch(request('/api/me'), {...env, IKIMONO_JS_SESSION: '0'});
assert.equal(forwarded.at(-1).url, origin + '/api/me');
const probe = await worker.fetch(request('/api/me', {'X-Ikimono-CPU-Probe': '0123abcd'}), env);
assert.match(probe.headers.get('X-Preview-Isolate'), /^[0-9a-f-]{36}$/);
assert.ok(Number(probe.headers.get('X-Preview-Isolate-Invocation')) > 1);
assert.equal((await worker.fetch(request('/health'), env)).status, 503, 'Stale backend presented as current');
const healthEnv = {...env, PYTHON: {async fetch() {return new Response('{}', {headers: {'X-Preview-Bundle-SHA256': pythonBundleDigest}});}}};
const health = await worker.fetch(request('/health'), healthEnv);
assert.equal(health.status, 200); assert.equal(health.headers.get('X-Preview-Backend-Bundle-SHA256'), pythonBundleDigest);
console.log('PASS: JS me avoids Python, existing cookie/config/security, Basic/Host/DB/flag guards, original proxy body/redirect/repeated cookies');
