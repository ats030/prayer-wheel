import assert from 'node:assert/strict';
import {Buffer} from 'node:buffer';
import {identify, validatePayload, jpegDimensions, prepareBinaryPayload} from '../worker_transport.mjs';
import {legacyValidate} from './legacy_payload_validator.mjs';

// Node24 lacks the Workers API. The shim is only used in this test process.
if (!Uint8Array.fromBase64) Uint8Array.fromBase64 = encoded => {
  const raw = Buffer.from(encoded, 'base64');
  if (raw.toString('base64') !== encoded) throw new TypeError('base64');
  return new Uint8Array(raw);
};
if (!Uint8Array.prototype.toBase64) Uint8Array.prototype.toBase64 = function () {
  return Buffer.from(this).toString('base64');
};
let input = '';
for await (const chunk of process.stdin) input += chunk;
const {template, good, large, badPhotos} = JSON.parse(input);
const expected = JSON.stringify(template);
const blob = payload => new Blob([JSON.stringify(payload)], {type: 'application/json'});
const payloadFor = images => ({...structuredClone(template), contents: [{role: 'user', parts: [
  ...images.map(data => ({inline_data: {mime_type: 'image/jpeg', data}})), ...structuredClone(template.contents[0].parts),
]}]});
const photoBlob = encoded => new Blob([Buffer.from(encoded, 'base64')], {type: 'image/jpeg'});
for (const photos of [[good], [good, good], [good, good, good], [large, large, large]]) {
  const result = await prepareBinaryPayload(photos.map(photoBlob), expected);
  assert.equal(result.type, 'application/json');
  assert.equal(await result.text(), JSON.stringify(payloadFor(photos)));
  await validatePayload(result, expected, photos.length);
}
for (const photos of [[], Array(4).fill(photoBlob(good)), ...badPhotos.map(value => [photoBlob(value)]),
  [new Blob([Buffer.from(good, 'base64')], {type: 'image/png'})], ['not-a-blob'],
  [new Blob([], {type: 'image/jpeg'})]]) await assert.rejects(prepareBinaryPayload(photos, expected));
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
let comparisons = 0;
const compare = async (text, count = 1, authoritative = expected) => {
  const input = new Blob([text], {type: 'application/json'});
  const accepted = async fn => {try {await fn(input, authoritative, count); return true;} catch {return false;}};
  assert.equal(await accepted(validatePayload), await accepted(legacyValidate), 'Legacy acceptance changed at case ' + comparisons);
  comparisons++;
};
for (const count of [1, 2, 3]) await compare(JSON.stringify(payloadFor(Array(count).fill(good))), count);
await compare(JSON.stringify(payloadFor([large, large, large])), 3);
for (const mutate of mutations) {const value = payloadFor([good]); mutate(value); await compare(JSON.stringify(value));}
for (const value of [correct + ' ', ' ' + correct, correct.replace('"contents":', '"contents":[],"contents":'),
  correct.replace('"data":', '"data":"ignored","data":'), correct.replace('image/jpeg', 'image\\/jpeg'),
  correct.replace('"data":', '"data" :'), correct.replace('"inline_data":', '"other":{},"inline_data":')]) await compare(value);
for (const encoded of [...badPhotos, '', '====', 'A===', good.slice(0, 4) + '=' + good.slice(5),
  good.slice(0, 4) + ' ' + good.slice(5), good + '=', good.slice(0, -1), good.slice(0, 4) + '\\n' + good.slice(4)])
  await compare(JSON.stringify(payloadFor([encoded])));
const bytes = Buffer.from(good, 'base64');
for (let i = 0; i < 128; i++) {
  const value = Buffer.from(bytes); value[(i * 37) % Math.min(bytes.length, 1000)] ^= 1 << (i % 8);
  await compare(JSON.stringify(payloadFor([value.toString('base64')])));
}
for (const length of [64000, 65000, 65340, 65400, 65500, 65520, 65530, 65534]) {
  const value = Buffer.concat([bytes.subarray(0, 2), Buffer.from([255, 226, length >> 8, length & 255]),
    Buffer.alloc(length - 2), bytes.subarray(2)]);
  await compare(JSON.stringify(payloadFor([value.toString('base64')])));
}
for (const padding of [0, 1, 2]) {
  const value = Buffer.concat([bytes.subarray(0, -2), Buffer.alloc(padding), bytes.subarray(-2)]).toString('base64');
  await compare(JSON.stringify(payloadFor([value])));
  if (value.endsWith('=')) {
    const index = value.length - (value.endsWith('==') ? 3 : 2);
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    const altered = value.slice(0, index) + alphabet[alphabet.indexOf(value[index]) ^ 1] + value.slice(index + 1);
    await compare(JSON.stringify(payloadFor([altered])));
  }
}
// The authoritative prompt can itself contain strings resembling our frame marker.
const nested = structuredClone(template); nested.contents[0].parts[0].text += '__ikimono_photo_parts__';
const nestedWire = structuredClone(payloadFor([good])); nestedWire.contents[0].parts[nestedWire.contents[0].parts.length - 1] = nested.contents[0].parts[0];
await compare(JSON.stringify(nestedWire), 1, JSON.stringify(nested));
assert.equal(await (await prepareBinaryPayload([photoBlob(good)], JSON.stringify(nested))).text(), JSON.stringify(nestedWire));
// A decoder must not silently remove a BOM inside the photo string.
const largeBytes = Buffer.from(large, 'base64');
const unpadded = Buffer.concat([largeBytes.subarray(0, -4), largeBytes.subarray(-2)]).toString('base64');
assert.ok(!unpadded.endsWith('='));
const bomPhoto = '\uFEFF' + unpadded.slice(0, 90000) + 'A' + unpadded.slice(90000);
await compare(JSON.stringify(payloadFor([bomPhoto])));
await assert.rejects(validatePayload(blob(payloadFor([bomPhoto])), expected, 1));
// Intentional tightening: malformed UTF-8 must not become a matching U+FFFD.
const replacement = structuredClone(template);
replacement.contents[0].parts[0].text += '\uFFFD';
const replacementWire = structuredClone(payloadFor([good]));
replacementWire.contents[0].parts.at(-1).text = replacement.contents[0].parts[0].text;
const malformed = Buffer.from(JSON.stringify(replacementWire));
const replacementOffset = malformed.indexOf(Buffer.from('\uFFFD'));
assert.ok(replacementOffset >= 0);
const malformedBlob = new Blob([Buffer.concat([malformed.subarray(0, replacementOffset),
  Buffer.from([255]), malformed.subarray(replacementOffset + 3)])], {type: 'application/json'});
await legacyValidate(malformedBlob, JSON.stringify(replacement), 1);
await assert.rejects(validatePayload(malformedBlob, JSON.stringify(replacement), 1));
console.log('PASS: ' + comparisons + ' legacy/new acceptance comparisons, base64 bits/padding and 64KiB JPEG boundary');
console.log('PASS: 1/3-photo wire parity, fixed endpoint, prompt/config/photo tamper rejection, provider status/output bounds');
