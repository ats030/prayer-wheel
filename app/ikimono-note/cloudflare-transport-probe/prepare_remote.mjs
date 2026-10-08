// Exact synthetic inputs from the checked original provider template.
import assert from 'node:assert/strict';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const health = await fetch('http://127.0.0.1:8793/health', {signal: AbortSignal.timeout(15000)});
assert.equal(health.headers.get('X-Probe-Synthetic-AI'), '1'); assert.equal(health.headers.get('X-Probe-Profile-IO'), '1');
const providerDigest = execFileSync('python3', ['-c', 'import json; from build import bundle_digest,HERE; print(bundle_digest(json.loads((HERE/"manifest.json").read_text())))'],
  {cwd: new URL('../cloudflare-app-probe/', import.meta.url), encoding: 'utf8'}).trim();
assert.equal(health.headers.get('X-Probe-Bundle-SHA256'), providerDigest, 'Stale provider template source');
const response = await fetch('http://127.0.0.1:8793/probe/profile/gemini-template', {signal: AbortSignal.timeout(15000)});
assert.equal(response.status, 200);
const {template, network_calls} = await response.json(); assert.equal(network_calls, 0);
const photo = await readFile(new URL('../cloudflare-app-probe/profile-fixtures/noise.jpg', import.meta.url));
const directory = new URL('./fixtures/', import.meta.url); await mkdir(directory, {recursive: true});
await writeFile(new URL('template.json', directory), JSON.stringify(template));
const provenance = {python_bundle_sha256: providerDigest,
  template_sha256: createHash('sha256').update(JSON.stringify(template)).digest('hex'),
  photo_sha256: createHash('sha256').update(photo).digest('hex'), fixtures: {}};
for (const count of [1, 3]) {
  const form = new FormData(); form.append('template', JSON.stringify(template));
  for (let i = 0; i < count; i++) form.append('files', new Blob([photo], {type: 'image/jpeg'}), 'synthetic.jpg');
  const request = new Request('http://localhost/payload', {method: 'POST', body: form});
  await writeFile(new URL(`multipart-${count}.bin`, directory), Buffer.from(await request.arrayBuffer()));
  await writeFile(new URL(`multipart-${count}.type`, directory), request.headers.get('Content-Type'));
  const payload = structuredClone(template);
  payload.contents[0].parts = [...Array.from({length: count}, () => ({inline_data: {mime_type: 'image/jpeg', data: photo.toString('base64')}})), template.contents[0].parts[1]];
  await writeFile(new URL(`wire-${count}.json`, directory), JSON.stringify(payload));
  for (const name of [`multipart-${count}.bin`, `multipart-${count}.type`, `wire-${count}.json`]) {
    provenance.fixtures[name] = createHash('sha256').update(await readFile(new URL(name, directory))).digest('hex');
  }
}
await writeFile(new URL('provenance.json', directory), JSON.stringify(provenance));
console.log('Prepared synthetic multipart and exact provider JSON fixtures; no external AI');
