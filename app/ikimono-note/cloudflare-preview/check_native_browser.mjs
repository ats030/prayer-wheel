// Local disposable browser context. Only template HTTP, never /identify or AI.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHmac} from 'node:crypto';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const origin = 'http://localhost:8795';
const secrets = JSON.parse(await readFile('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json', 'utf8'));
const body = Buffer.from(JSON.stringify({sub: 'synthetic-native-browser-check', email: 'synthetic@example.invalid', exp: Math.floor(Date.now()/1000)+300})).toString('base64url');
const cookie = body + '.' + createHmac('sha256', secrets.IKIMONO_SESSION_SECRET).update(body).digest('base64url');
const browser = await chromium.launch({headless: true});
try {
  const context = await browser.newContext({httpCredentials: {username: 'preview', password: secrets.IKIMONO_PREVIEW_PASSWORD}});
  await context.addCookies([{name: 'ikimono_session', value: cookie, url: origin}]);
  // Fail closed if this browser test ever tries to identify or contact a provider.
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === origin && url.pathname !== '/identify' ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  await page.goto(origin + '/health');
  const results = await page.evaluate(async () => {
    const {appendPreparedPhotos} = await import('/assets/photo-browser.mjs');
    const {appendNativeGeminiPayload} = await import('/assets/provider-payload.mjs');
    const settings = await fetch('/api/settings').then(response => response.json());
    const model = settings.available_models.gemini[0].id;
    const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 450;
    const ctx = canvas.getContext('2d');
    for (let y = 0; y < 450; y += 10) for (let x = 0; x < 600; x += 10) {
      ctx.fillStyle = ((x+y)/10)%2 ? '#709050' : '#c0b050'; ctx.fillRect(x,y,10,10);
    }
    const photo = new File([await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg'))], 'synthetic.jpg', {type: 'image/jpeg'});
    const results = [];
    for (const count of [1,3]) {
      const form = new FormData();
      form.set('request_model', model); form.set('request_provider', 'gemini'); form.set('request_api_key', 'synthetic-never-forward');
      form.set('location', '山麓'); form.set('observed_date', '2026-10-09'); form.set('size', '約5cm');
      await appendPreparedPhotos(form, Array(count).fill(photo));
      const reports = form.get('client_photos');
      await appendNativeGeminiPayload(form);
      const payloadFile = form.get('provider_payload');
      const payload = JSON.parse(await payloadFile.text());
      results.push({count, files: form.getAll('files').length, parts: payload.contents[0].parts.length,
        type: payloadFile.type, unchanged: form.get('client_photos') === reports,
        photos: payload.contents[0].parts.slice(0,count).every(part => part.inline_data.mime_type === 'image/jpeg'),
        context: payload.contents[0].parts.at(-1).text.includes('山麓') && payload.contents[0].parts.at(-1).text.includes('2026-10-09')});
    }
    return results;
  });
  for (const item of results) {
    assert.equal(item.files, 0); assert.equal(item.parts, item.count+1); assert.equal(item.type, 'application/json');
    assert.ok(item.unchanged && item.photos && item.context);
  }
  await context.close();
  console.log('PASS: browser prepared JPEGs, 1/3-photo native payload, authenticated templates, metadata/context retained; no identify/provider HTTP');
} finally {await browser.close();}
