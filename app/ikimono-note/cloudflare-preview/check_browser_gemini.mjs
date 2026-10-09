// Local full UI + existing IndexedDB save, with all provider HTTP intercepted.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHmac} from 'node:crypto';
import {chromium} from '../../dekita/node_modules/playwright/index.mjs';
const origin = process.argv[2] || 'http://localhost:8795';
assert.ok(['http://localhost:8795','https://ikimono-note-preview.ats030.workers.dev'].includes(origin),'Unsupported check origin');
const secrets = JSON.parse(await readFile('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json', 'utf8'));
const body = Buffer.from(JSON.stringify({sub: 'synthetic-browser-gemini-check', email: 'synthetic@example.invalid',
  exp: Math.floor(Date.now()/1000)+300})).toString('base64url');
const cookie = body + '.' + createHmac('sha256', secrets.IKIMONO_SESSION_SECRET).update(body).digest('base64url');
const key = 'synthetic-never-forward-key';
const expectedDigest=JSON.parse(await readFile(new URL('./edge-manifest.json',import.meta.url),'utf8')).bundle_sha256;
const browser = await chromium.launch({headless: true});
try {
  for (const count of [1, 3]) {
    const context = await browser.newContext({httpCredentials: {username: 'preview', password: secrets.IKIMONO_PREVIEW_PASSWORD}});
    await context.addCookies([{name: 'ikimono_session', value: cookie, url: origin}]);
    await context.addInitScript(key => {
      sessionStorage.setItem('species-key-gemini', key);
      localStorage.setItem('species-public-settings', JSON.stringify({provider: 'gemini'}));
    }, key);
    let providerCalls = 0, prepareCalls = 0, resultCalls = 0, jsResponses = 0;
    const bundleHashes=[];
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin === origin) {
        assert.notEqual(url.pathname, '/identify', 'Photo relay must not be used');
        if (request.method() === 'POST') {
          assert.ok(['/api/gemini/prepare', '/api/gemini/result'].includes(url.pathname));
          const text = request.postData() || '';
          assert.ok(!text.includes(key) && !text.includes('inline_data'));
          assert.equal(JSON.parse(text).count, count);
          if (url.pathname.endsWith('/prepare')) prepareCalls++;
          else resultCalls++;
        }
        return route.continue({headers:{...request.headers(), ...(url.pathname.startsWith('/api/gemini/')?
          {'X-Ikimono-CPU-Probe':'030cafe0'}:{})}});
      }
      if (url.origin === 'https://generativelanguage.googleapis.com') {
        providerCalls++;
        assert.match(url.pathname, /^\/v1beta\/models\/gemini-[a-zA-Z0-9._-]+:generateContent$/);
        assert.equal(request.headers()['x-goog-api-key'], key);
        assert.equal(request.headers().authorization, undefined);
        const payload = JSON.parse(request.postData());
        assert.equal(payload.contents[0].parts.length, count+1);
        assert.ok(payload.contents[0].parts.slice(0,count).every(part => part.inline_data.mime_type === 'image/jpeg'));
        return route.fulfill({status: 200, contentType: 'application/json',
          headers: {'Access-Control-Allow-Origin': origin},
          body: JSON.stringify({candidates: [{content: {parts: [{text: '{"category":"不明","summary":"観察","candidates":[]}'}]}}]})});
      }
      return route.abort(); // Never contact any external provider/DB/Drive.
    });
    const page = await context.newPage();
    page.on('response', response => {
      if(new URL(response.url()).pathname.startsWith('/api/gemini/') && response.headers()['x-preview-gemini-engine']==='javascript'){
        jsResponses++;bundleHashes.push(response.headers()['x-preview-bundle-sha256']);
      }
    });
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto(origin + '/');
    await page.waitForFunction(() => window.speciesBrowserGemini === true);
    assert.ok((await page.request.get(origin + '/')).headers()['content-security-policy'].includes('https://generativelanguage.googleapis.com'));
    const photo = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = 600; canvas.height = 450;
      const ctx = canvas.getContext('2d');
      for (let y = 0; y < 450; y += 10) for (let x = 0; x < 600; x += 10) {
        ctx.fillStyle = ((x+y)/10)%2 ? '#709050' : '#c0b050'; ctx.fillRect(x,y,10,10);
      }
      return canvas.toDataURL('image/jpeg').split(',')[1];
    });
    await page.locator('#library').setInputFiles(Array.from({length: count}, (_, index) => ({
      name: `synthetic-${index}.jpg`, mimeType: 'image/jpeg', buffer: Buffer.from(photo, 'base64')})));
    await page.locator('#identify').waitFor({state: 'visible'});
    await page.evaluate(() => {document.getElementById('observedDate').value = '2026-10-09';});
    await page.locator('#identify').click();
    await page.waitForFunction(() => document.getElementById('status').textContent.includes('似ている生きものを表示しました'));
    // Rendering precedes saveHistory's awaited image conversion/transaction.
    // Observe its completion rather than treating the first rendered frame as
    // proof that IndexedDB has committed the record.
    await page.evaluate(async () => {
      const deadline = Date.now()+10000;
      while (Date.now() < deadline) {
        const open = indexedDB.open('species-history', 1);
        const db = await new Promise(resolve => {open.onsuccess = () => resolve(open.result);});
        let saved = false;
        if (db.objectStoreNames.contains('entries')) {
          const request = db.transaction('entries').objectStore('entries').getAll();
          const rows = await new Promise(resolve => {request.onsuccess = () => resolve(request.result);});
          saved = rows.length === 1;
        }
        db.close();
        if (saved) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error('IndexedDB save did not complete');
    });
    const records = await page.evaluate(async () => {
      const db = await new Promise(resolve => {const r=indexedDB.open('species-history',1); r.onsuccess=()=>resolve(r.result);});
      const request = db.transaction('entries').objectStore('entries').getAll();
      const rows = await new Promise(resolve => {request.onsuccess=()=>resolve(request.result);});
      db.close(); return rows.map(row => ({count: row.thumbnails.length, strict: row.resultMeta.strictMode,
        taxonomy: row.resultMeta.taxonomyChecked, date: row.context.observedDate, model: row.model}));
    });
    if (records.length !== 1 || records[0].count !== count) {
      const diagnosis = await page.evaluate(async () => {
        try {const saved = await pendingPhotos(selected); return {saved: saved.length, selected: selected.length,
          helper: typeof shrinkForHistory, converter: typeof blobToDataUrl};}
        catch (error) {return {error: error.message};}
      });
      assert.fail('Photo save mismatch: ' + JSON.stringify({records, diagnosis, pageErrors, providerCalls, prepareCalls, resultCalls}));
    }
    assert.ok(records[0].strict && records[0].taxonomy); assert.equal(records[0].date, '2026-10-09');
    assert.equal(providerCalls, 1); assert.equal(prepareCalls, 1); assert.equal(resultCalls, 1);
    assert.equal(jsResponses,2,'Gemini APIs did not use the native JS entrypoint');
    assert.deepEqual(bundleHashes,[expectedDigest,expectedDigest],'Browser used a stale deployment');
    await context.close();
  }
  console.log('PASS: real browser 1/3 photos direct Gemini mock, real auth/quality/template/finish, metadata and all photos saved in isolated IndexedDB; zero external AI');
} finally {await browser.close();}
