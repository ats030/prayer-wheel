import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {webcrypto, createHash} from 'node:crypto';
import worker, {adsEnabled, bucket, ExternalAPI, extractBlocks, GeocodingGate, hotelLink, officialSite, sha} from '../cloudflare/worker.mjs';
globalThis.crypto ||= webcrypto;
const origin = 'https://midokoro-map.ats030.workers.dev';
const env = {
  MIDOKORO_PUBLIC_ORIGIN: origin,
  MIDOKORO_AFFILIATE_ORIGINS: '',
  ASSETS: {async fetch(request) {
    try { return new Response(await readFile(new URL('../cloudflare/assets' + new URL(request.url).pathname, import.meta.url))); }
    catch { return new Response(null, {status: 404}); }
  }}
};
const request = (path, options) => new Request(origin + path, options);
test('All four published lists and item indices retain the Go snapshots', async () => {
  for (const [kind, name] of [['omatsuri', 'festivals'], ['onsen', 'onsen'], ['shiseki', 'shiseki'], ['tokusan', 'tokusan']]) {
    const response = await worker.fetch(request(`/api/${kind}/${name}/`), env);
    assert.equal(response.status, 200);
    const rows = await response.json();
    const snapshot = JSON.parse(await readFile(new URL(`../cloudflare/assets/_data/${kind}/list.json`, import.meta.url), 'utf8'));
    assert.ok(rows.length > 0);
    assert.deepEqual(rows, snapshot);
    const row = rows.find(r => r.qid);
    assert.deepEqual(await (await worker.fetch(request(`/api/${kind}/${name}/${row.qid}`), env)).json(), kind === 'onsen' ? rows : row);
    const filtered = await (await worker.fetch(request(`/api/${kind}/${name}/prefecture/${encodeURIComponent(row.prefecture)}`), env)).json();
    assert.deepEqual(filtered, rows.filter(r => r.prefecture === row.prefecture));
  }
});
test('Private artifacts and invalid routes never become a SPA response', async () => {
  for (const path of ['/_data/shiseki/cache/00.json', '/api/unknown/onsen/', '/api/onsen/unknown', '/api/tokusan/tokusan/not-real']) assert.equal((await worker.fetch(request(path), env)).status, 404);
  assert.equal((await worker.fetch(request('/api/onsen/onsen/', {method: 'POST'}), env)).status, 405);
});
test('Advertising requires registered HTTPS origin and same-origin consumer', async () => {
  const enabled = {...env, MIDOKORO_AFFILIATE_ORIGINS: origin, MIDOKORO_ONSEN_A8MAT: 'test-tracking'};
  assert.equal(adsEnabled(request('/'), enabled), true);
  assert.equal(adsEnabled(new Request('https://alternate.test/'), enabled), false);
  assert.equal(adsEnabled(request('/', {headers: {Origin: 'https://other.test'}}), enabled), false);
  const p = '/api/onsen/hotel-area/nearby?prefecture=' + encodeURIComponent('群馬県') + '&lrg_code=090200&lrg_name=草津&sml_code=090202&sml_name=湯畑';
  const ordinary = await hotelLink(request(p), env, 'onsen').json();
  assert.equal(ordinary.hotels[0].detail_url, 'https://www.jalan.net/090000/LRG_090200/SML_090202/');
  const ad = await hotelLink(request(p), enabled, 'onsen').json();
  assert.equal(new URL(ad.hotels[0].detail_url).searchParams.get('a8ejpredirect'), ordinary.hotels[0].detail_url);
});
test('Story telemetry preserves fixed vocabulary, empty body and same-origin boundary', async () => {
  const path = '/api/story-events/arita-porcelain/view';
  assert.equal((await worker.fetch(request(path, {method: 'POST'}), env)).status, 204);
  assert.equal((await worker.fetch(request(path + '?id=1', {method: 'POST'}), env)).status, 404);
  assert.equal((await worker.fetch(request(path, {method: 'POST', body: '{}'}), env)).status, 400);
  assert.equal((await worker.fetch(request(path, {method: 'POST', headers: {'Sec-Fetch-Site': 'cross-site'}}), env)).status, 403);
  assert.equal((await worker.fetch(request(path), env)).status, 405);
});
test('Geocoding rejects invalid bodies before upstream calls; gate persists no coordinates', async () => {
  assert.equal((await worker.fetch(request('/api/onsen/geocoding/reverse', {method: 'POST', body: '{"lat":91,"lng":0}'}), env)).status, 400);
  const stored = new Map();
  const storage = {get: async k => stored.get(k), put: async (k, v) => stored.set(k, v)};
  const gate = new GeocodingGate({storage});
  const originalFetch = globalThis.fetch, times = [];
  globalThis.fetch = async () => { times.push(Date.now()); return Response.json({address: {city: '草津町'}}); };
  try {
    const req = () => new Request('https://gate.internal/', {method: 'POST', body: JSON.stringify({lat: 36.6, lng: 138.6})});
    await Promise.all([gate.fetch(req()), gate.fetch(req())]);
    assert.ok(times[1] - times[0] >= 1000);
    assert.deepEqual([...stored.keys()], ['next']);
    gate.waiting = 10;
    assert.equal((await gate.fetch(req())).status, 429);
  } finally { globalThis.fetch = originalFetch; }
});
test('Section extraction retains nested headings and stops at sibling headings', () => {
  const headings = [{line: '歴史', level: 2}, {line: '江戸', level: 3}, {line: '交通', level: 2}];
  assert.deepEqual(extractBlocks('導入\n歴史\n古い記録\n江戸\n町が発展\n交通\n電車', headings[0], headings, 600), [{heading: '', text: '古い記録'}, {heading: '江戸', text: '町が発展'}]);
  assert.deepEqual(extractBlocks('導入\n歴史\n古い記録', null, headings, 600), [{heading: '', text: '導入'}]);
});
test('Wikipedia official-site fallback only reads the existing external-link context', () => {
  assert.equal(officialSite('出典 https://unrelated.test/\n| 外部リンク = [https://official.test/ 公式]'), 'https://official.test/');
  assert.equal(officialSite('出典 https://unrelated.test/'), '');
  assert.equal(officialSite('| 外部リンク = https://ja.wikipedia.org/wiki/test'), '');
});
test('Cache hashes match existing Go SHA256 contracts', async () => {
  assert.equal(await sha('草津温泉|歴史 v3'), createHash('sha256').update('草津温泉|歴史 v3').digest('hex'));
  assert.ok(/^[0-3][0-9a-f]$/.test(bucket('Q123')));
});
test('Wikipedia identity, summaries, attribution and transient failures remain distinct', async () => {
  const originalFetch = globalThis.fetch;
  const cacheKey = await sha('検証温泉|歴史 v3');
  const testEnv = {...env, ASSETS: {async fetch(r) {
    if (new URL(r.url).pathname === `/_data/onsen/cache/${cacheKey.slice(0, 2)}.json`) return Response.json({[cacheKey]: JSON.stringify({summary: '資料から得た要約。', items: [{label: '江戸', value: '記録がある。'}]})});
    return env.ASSETS.fetch(r);
  }}};
  let mismatch = false, brokenSections = false;
  globalThis.fetch = async input => {
    const url = new URL(input), p = url.searchParams;
    if (p.get('action') === 'parse') return Response.json(brokenSections ? {error: {code: 'maxlag'}} : {parse: {sections: [{line: '歴史', level: '2'}]}});
    if (p.get('action') === 'wbgetentities') return Response.json({entities: {Q1: {claims: {}}}});
    if (url.hostname === 'commons.wikimedia.org') return Response.json({query: {pages: {'1': {imageinfo: [{url: 'https://upload.wikimedia.org/test.jpg', mime: 'image/jpeg', descriptionurl: 'https://commons.wikimedia.org/wiki/File:Test.jpg', extmetadata: {LicenseShortName: {value: 'CC BY 4.0'}, LicenseUrl: {value: 'https://creativecommons.org/licenses/by/4.0/'}, Artist: {value: '撮影者'}}}]}}}});
    return Response.json({query: {pages: [{title: '検証温泉', extract: p.has('exintro') ? '温泉の概要。' : '温泉の概要。\n歴史\n原文の歴史。', pageprops: {wikibase_item: mismatch ? 'Q2' : 'Q1'}, pageimage: 'Test.jpg'}]}});
  };
  try {
    const path = '/api/onsen/wiki/content?title=検証温泉&qid=Q1';
    const result = await (await worker.fetch(request(path), testEnv)).json();
    assert.equal(result.description, '温泉の概要。');
    assert.equal(result.history.summary, '資料から得た要約。');
    assert.equal(result.history.items[0].label, '江戸');
    assert.equal(result.history.blocks, undefined);
    assert.equal(result.license, 'CC BY 4.0');
    brokenSections = true;
    assert.equal((await (await worker.fetch(request(path), testEnv)).json()).sections_unavailable, true);
    mismatch = true;
    assert.equal((await worker.fetch(request(path), testEnv)).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});
test('Geo natural monuments use geo specs, the geo cache and shiseki response slots', async () => {
  const originalFetch = globalThis.fetch;
  const extract = '洞の概要。\n成因\n溶岩が冷えて柱状節理ができた。\n岩の様子\n六角柱が並ぶ。';
  const cacheKey = await sha('検証洞|成り立ち|' + extract), featuresKey = await sha('検証洞|特徴・見どころ|' + extract);
  let sections = [{line: '成因', level: '2'}];
  const headingKey = () => sha('headingmap|geo-v1|検証洞|' + sections.map(s => s.line).sort().join('\n'));
  const specs = {geo_heading_prefix: 'geo-v1|', geo: [{key: 'origin', label: '成り立ち', candidates: ['成因']}, {key: 'features', label: '特徴・見どころ', candidates: ['特徴']},
    {key: 'access', label: 'アクセス', candidates: ['アクセス']}, {key: 'protection', label: '指定・保護', candidates: ['指定']}]};
  const testEnv = {...env, ASSETS: {async fetch(r) {
    const path = new URL(r.url).pathname;
    if (path === '/_data/specs.json') return Response.json(specs);
    if (path.startsWith('/_data/geo/cache/')) {
      const entries = {[cacheKey]: '溶岩が冷えて柱状節理になった。', [featuresKey]: '六角柱の岩が並ぶ。', [await headingKey()]: JSON.stringify({features: '岩の様子'})};
      return Response.json(Object.fromEntries(Object.entries(entries).filter(([key]) => path.endsWith(`/${key.slice(0, 2)}.json`))));
    }
    return env.ASSETS.fetch(r);
  }}};
  globalThis.fetch = async input => {
    const p = new URL(input).searchParams;
    if (p.get('action') === 'parse') return Response.json({parse: {sections}});
    if (p.get('action') === 'wbgetentities') return Response.json({entities: {Q1: {claims: {}}}});
    return Response.json({query: {pages: [{title: '検証洞', extract: p.has('exintro') ? '洞の概要。' : extract, pageprops: {wikibase_item: 'Q1'}}]}});
  };
  try {
    const result = await (await worker.fetch(request('/api/geo/wiki/content?title=検証洞&qid=Q1'), testEnv)).json();
    assert.equal(result.description, '洞の概要。');
    assert.equal(result.history.summary, '溶岩が冷えて柱状節理になった。');
    assert.equal(result.history.blocks, undefined);
    assert.equal(result.origin, undefined);
    assert.deepEqual(result.remains, {});
    assert.equal((await worker.fetch(request('/api/geo/wiki/content?qid=Q1'), testEnv)).status, 400);
    assert.equal((await worker.fetch(request('/api/geo/wiki/image?qid=undefined'), testEnv)).status, 400);
    // A heading the model mapped (cached under the versioned geo heading key) also finds its summary.
    sections = [{line: '成因', level: '2'}, {line: '岩の様子', level: '2'}];
    const mapped = await (await worker.fetch(request('/api/geo/wiki/content?title=検証洞&qid=Q1'), testEnv)).json();
    assert.equal(mapped.remains.summary, '六角柱の岩が並ぶ。');
    assert.equal((await worker.fetch(request('/api/geo/wiki/links?qid=Q1'), testEnv)).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});
test('Festival photo fallback uses label/prefecture, exact filenames and license fallback', async () => {
  const originalFetch = globalThis.fetch;
  let mismatch = false, mime = 'image/jpeg';
  globalThis.fetch = async input => {
    const p = new URL(input).searchParams;
    if (p.get('generator') === 'search') {
      assert.equal(p.get('gsrsearch'), '検証祭 群馬県');
      return Response.json({query: {pages: [{title: 'File:' + (mismatch ? '別の祭り.jpg' : '検証祭.jpg')}]}});
    }
    return Response.json({query: {pages: {'1': {imageinfo: [{url: 'https://upload.wikimedia.org/photo.jpg', mime, descriptionurl: 'https://commons.wikimedia.org/wiki/File:photo.jpg', extmetadata: {License: {value: 'CC BY 4.0'}, AttributionRequired: {value: 'true'}}}]}}}});
  };
  try {
    const path = '/api/omatsuri/commons/image?label=検証祭&prefecture=群馬県';
    const photo = await (await worker.fetch(request(path), env)).json();
    assert.equal(photo.image_url, 'https://upload.wikimedia.org/photo.jpg');
    assert.equal(photo.license, 'CC BY 4.0');
    assert.equal(photo.attribution_required, true);
    assert.ok(photo.image_source_url);
    mismatch = true;
    assert.equal((await worker.fetch(request(path), env)).status, 404);
    mismatch = false; mime = 'image/svg+xml';
    assert.equal((await worker.fetch(request(path), env)).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});
test('Heavy APIs use Durable Objects while public lists stream from assets', async () => {
  let calls = 0;
  const forwarded = {...env, EXTERNAL_API: {
    idFromName(name) { assert.match(name, /^[0-9a-f]{64}$/); return name; },
    get() { calls++; return new ExternalAPI({}, env); }
  }};
  const path = '/api/tokusan/sections/local-5aba329a3305884a';
  assert.deepEqual(await (await worker.fetch(request(path), forwarded)).json(), await (await worker.fetch(request(path), env)).json());
  assert.equal(calls, 1);
  assert.equal((await worker.fetch(request('/api/shiseki/shiseki/'), forwarded)).status, 200);
  assert.equal(calls, 1);
});
