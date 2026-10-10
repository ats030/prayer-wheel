import assert from 'node:assert/strict';
import worker from '../cloudflare-preview/edge.mjs';
const origin = 'https://ikimono-note.ats030.workers.dev';
const env = {IKIMONO_LOGIN_REQUIRED:'0', IKIMONO_SESSION_SECRET:'synthetic-session',
  IKIMONO_ALLOWED_HOSTS:new URL(origin).hostname, IKIMONO_PUBLIC_ORIGIN:origin,
  IKIMONO_GOOGLE_CLIENT_ID:'synthetic-id', IKIMONO_GOOGLE_CLIENT_SECRET:'synthetic-key',
  IKIMONO_JS_SESSION:'1', IKIMONO_JS_GEMINI:'1', DB:{},
  PYTHON:{async fetch(){return new Response('backend');}}};
const request = path => new Request(origin+path);
assert.equal((await worker.fetch(request('/api/me'),env)).status,200);
assert.equal((await worker.fetch(request('/history'),env)).status,200);
for(const flag of [undefined,'1','false','']) {
  assert.equal((await worker.fetch(request('/api/me'),{...env,IKIMONO_LOGIN_REQUIRED:flag,
    IKIMONO_PREVIEW_PASSWORD:'synthetic-password'})).status,401);
}
assert.equal((await worker.fetch(request('/api/me'),{...env,IKIMONO_SESSION_SECRET:''})).status,503);
assert.equal((await worker.fetch(new Request(origin+'/api/me',{headers:{Host:'attacker.invalid'}}),env)).status,400);
// A malformed prepare must reach validation (400), not the session gate (401).
const response=await worker.fetch(new Request(origin+'/api/gemini/prepare',{
  method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),env);
assert.equal(response.status,400);
const {default:policy}=await import('../cloudflare-preview/_gemini_policy.mjs');
const prepared=await worker.fetch(new Request(origin+'/api/gemini/prepare',{
  method:'POST',headers:{'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.190'},
  body:JSON.stringify({model:policy.models[0],count:1,client_photos:JSON.stringify([
    {metadata:{observed_date:'2026-10-10'},measured:{width:600,height:450,pixels:270000,
      brightness:120,sharpness:200,contrast:30}}])})}),env);
assert.equal(prepared.status,200);
assert.ok((await prepared.json()).contents[0].parts[0].text.includes('2026-10-10'));
console.log('PASS: explicit guest access, protected default, host/session guards, anonymous Gemini validation');
