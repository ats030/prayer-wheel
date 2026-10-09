import assert from 'node:assert/strict';
import {Buffer} from 'node:buffer';
import {identify, validatePayload, jpegDimensions} from '../worker_transport.mjs';

// Node24 lacks the Workers API. The shim is only used in this test process.
if (!Uint8Array.fromBase64) Uint8Array.fromBase64 = encoded => {
  const raw = Buffer.from(encoded, 'base64');
  if (raw.toString('base64') !== encoded) throw new TypeError('base64');
  return new Uint8Array(raw);
};
let input = '';
for await (const chunk of process.stdin) input += chunk;
const {template, good, large, badPhotos} = JSON.parse(input);
const expected = JSON.stringify(template);
const blob = payload => new Blob([JSON.stringify(payload)], {type: 'application/json'});
const payloadFor = images => ({...structuredClone(template), contents: [{role: 'user', parts: [
  ...images.map(data => ({inline_data: {mime_type: 'image/jpeg', data}})), ...structuredClone(template.contents[0].parts),
]}]});
let calls = 0;
for (const count of [1, 3]) {
  const payload = payloadFor(Array(count).fill(good));
  const wire = blob(payload);
  const fetcher = async (url, options) => {
    calls++;
    assert.equal(url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent');
    assert.equal(options.headers['x-goog-api-key'], 'own-key');
    assert.equal(options.redirect, 'error');
    assert.equal(await new Response(options.body).text(), await wire.text());
    return Response.json({candidates: [{content: {parts: [{text: '{}'}]}}]});
  };
  const reply = JSON.parse(await identify(wire, expected, count, 'gemini-test', 'own-key', fetcher));
  assert.equal(reply.status, 200);
  assert.equal(reply.data.candidates[0].content.parts[0].text, '{}');
}
assert.equal(calls, 2);
// Exercise the maximum photo size without regex recursion or provider HTTP.
await validatePayload(blob(payloadFor([large, large, large])), expected, 3);
const forbidden = async () => {throw new Error('Invalid input attempted provider HTTP');};
const mutations = [
  payload => {payload.contents[0].parts.at(-1).text += 'modified';},
  payload => {payload.generationConfig.temperature = 1;},
  payload => {payload.generationConfig.maxOutputTokens++;},
  payload => {payload.contents[0].role = 'model';},
  payload => {payload.systemInstruction = {parts: [{text: 'override'}]};},
  payload => {payload.contents[0].parts[0].inline_data.mime_type = 'image/png';},
  payload => {payload.contents[0].parts[0].file_data = {file_uri: 'https://example.invalid/'};},
  payload => {payload.contents.push({role: 'user', parts: [{text: 'extra'}]});},
  payload => {payload.contents[0].parts[0].inline_data.data = 'AA==';},
];
for (const mutate of mutations) {
  const payload = payloadFor([good]); mutate(payload);
  assert.equal(JSON.parse(await identify(blob(payload), expected, 1, 'gemini-test', 'own-key', forbidden)).error, 'input');
}
for (const photo of badPhotos) {
  assert.equal(JSON.parse(await identify(blob(payloadFor([photo])), expected, 1, 'gemini-test', 'own-key', forbidden)).error, 'input');
}
for (const count of [0, 2, 4]) {
  assert.equal(JSON.parse(await identify(blob(payloadFor([good])), expected, count, 'gemini-test', 'own-key', forbidden)).error, 'input');
}
const correct = JSON.stringify(payloadFor([good]));
for (const text of [correct + ' ', '{"contents":[],"contents":' + correct.slice('{"contents":'.length)]) {
  assert.equal(JSON.parse(await identify(new Blob([text], {type: 'application/json'}), expected, 1, 'gemini-test', 'own-key', forbidden)).error, 'input');
}
for (const model of ['../wrong', 'model?key=bad']) {
  assert.equal(JSON.parse(await identify(blob(payloadFor([good])), expected, 1, model, 'own-key', forbidden)).error, 'input');
}
const validBlob = blob(payloadFor([good]));
for (const status of [401, 403, 429, 500]) {
  assert.deepEqual(JSON.parse(await identify(validBlob, expected, 1, 'gemini-test', 'own-key', async () => new Response('private provider detail', {status}))), {status});
}
for (const fetcher of [async () => {throw new Error('private connection detail');},
  async () => new Response('not-json'), async () => new Response('[]'), async () => new Response('null'),
  async () => new Response('"text"'), async () => new Response('x'.repeat(2 * 1024 * 1024 + 1))]) {
  assert.deepEqual(JSON.parse(await identify(validBlob, expected, 1, 'gemini-test', 'own-key', fetcher)), {error: 'connection'});
}
assert.deepEqual(jpegDimensions(Uint8Array.fromBase64(good)), [600, 450]);
await validatePayload(validBlob, expected, 1);
console.log('PASS: 1/3-photo wire parity, fixed endpoint, prompt/config/photo tamper rejection, provider status/output bounds');
