import assert from 'node:assert/strict';
import {identifyWithBrowserGemini} from '../static/assets/gemini-browser.mjs';
import {assembleProviderPayload} from '../static/assets/provider-payload.mjs';
import {Buffer} from 'node:buffer';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const {template, good, large, badPhotos} = JSON.parse(input);
const reply = {candidates: [{content: {parts: [{text: '{"category":"不明","candidates":[]}'}]}}]};
const final = {provider: 'gemini', strict_mode: true, candidates: [], photo_metadata: {observed_date: '2026-10-09'}};
const model = 'gemini-test', key = 'synthetic-own-key';
function form(photos = [good]) {
  const value = new FormData();
  for (const photo of photos) value.append('files', new Blob([Buffer.from(photo, 'base64')], {type: 'image/jpeg'}), 'synthetic.jpg');
  for (const [name, text] of Object.entries({request_provider: 'gemini', request_model: model, request_api_key: ' ' + key + ' ',
    client_photos: '[]', location: '山麓', observed_date: '2026-10-09', size: '約5cm', use_plantnet: 'false'})) value.set(name, text);
  return value;
}
for (const photos of [[good], [good, good, good], [large, large, large]]) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push(url);
    assert.equal(options.redirect, 'error');
    if (url === '/api/gemini/prepare' || url === '/api/gemini/result') {
      assert.equal(options.credentials, 'same-origin');
      assert.ok(!options.body.includes(key));
      assert.ok(!options.body.includes('inline_data'));
      const body = JSON.parse(options.body);
      assert.equal(body.count, photos.length); assert.equal(body.model, model);
      if (url.endsWith('/prepare')) return Response.json(template);
      assert.deepEqual(JSON.parse(body.reply), reply);
      return Response.json(final);
    }
    assert.equal(url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent');
    assert.equal(options.headers['x-goog-api-key'], key);
    assert.equal(options.credentials, 'omit'); assert.equal(options.referrerPolicy, 'no-referrer'); assert.equal(options.mode, 'cors');
    assert.equal(options.body, JSON.stringify(assembleProviderPayload('gemini', template, photos)));
    return Response.json(reply);
  };
  assert.deepEqual(await identifyWithBrowserGemini(form(photos), fetcher), final);
  assert.equal(calls.length, 3);
}
for (const [status, message] of [[401, 'APIキー'], [403, 'APIキー'], [429, '利用上限'], [500, '500']]) {
  let calls = 0;
  await assert.rejects(identifyWithBrowserGemini(form(), async url => {
    calls++;
    if (url === '/api/gemini/prepare') return Response.json(template);
    assert.ok(url.startsWith('https://generativelanguage.googleapis.com/'));
    return new Response('private provider detail', {status});
  }), error => error.message.includes(message) && !error.message.includes('private'));
  assert.equal(calls, 2); // No retries or result submission after quota/error.
}
for (const photo of badPhotos) {
  let providerCalls = 0;
  await assert.rejects(identifyWithBrowserGemini(form([photo]), async url => {
    if (url === '/api/gemini/prepare') return Response.json(template);
    providerCalls++; throw new Error('Must not forward invalid JPEG');
  }));
  assert.equal(providerCalls, 0);
}
for (const [field, value] of [['request_api_key', ''], ['request_model', '../wrong'], ['request_provider', 'openai'], ['use_plantnet', 'true']]) {
  const valueForm = form(); valueForm.set(field, value);
  await assert.rejects(identifyWithBrowserGemini(valueForm, async () => {assert.fail('Unexpected HTTP');}));
}
for (const status of [401, 422, 429]) {
  let calls = 0;
  await assert.rejects(identifyWithBrowserGemini(form(), async url => {
    calls++; assert.equal(url, '/api/gemini/prepare');
    return Response.json({detail: {message: 'blocked'}}, {status});
  }), /blocked/);
  assert.equal(calls, 1);
}
let canceled = false;
await assert.rejects(identifyWithBrowserGemini(form(), async url => url === '/api/gemini/prepare'
  ? Response.json(template) : new Response(new ReadableStream({start(controller) {
    controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
  }, cancel() {canceled = true;}}))), /応答/);
assert.ok(canceled);
console.log('PASS: browser Gemini byte parity, key/photos only to fixed provider, server auth/quality before AI, quota stop and output bound');
