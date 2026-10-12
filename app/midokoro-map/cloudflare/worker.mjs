// Public API adapter. The local SQLite databases and model remain the source of truth.
const kinds = ['shiseki', 'omatsuri', 'onsen', 'tokusan'];
const collections = {shiseki: 'shiseki', omatsuri: 'festivals', onsen: 'onsen', tokusan: 'tokusan'};
// Geo natural monuments use the shiseki cache scheme with their own specs; specs fill these response slots in order.
const geoSlots = ['history', 'remains', 'access', 'highlights'];
const summaryKeyed = kind => kind === 'shiseki' || kind === 'geo';
const slugs = ['arita-porcelain', 'kusatsu-yumomi', 'kawagoe-festival'];
const events = ['view', 'entry-home', 'entry-shared', 'explore', 'follow', 'share-open', 'share-returned', 'copy-success'];
const userAgent = 'midokoro-map/1.0 (https://github.com/ats030/ikimono-note)';
// Match Go url.PathEscape, including parentheses and punctuation used by titles.
const pathEscape = value => encodeURIComponent(value).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase()).replace(/%2B|%3A|%40|%26|%3D|%24/g, c => decodeURIComponent(c));
const articleURL = title => 'https://ja.wikipedia.org/wiki/' + pathEscape(title.replaceAll(' ', '_'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
export const json = (value, status = 200, headers = {}) => Response.json(value, {status, headers: {'Cache-Control': 'no-store', ...headers}});
const error = (message, status) => json({error: message}, status);
export function bucket(id) {
  let n = 0;
  for (const b of new TextEncoder().encode(id)) n = (Math.imul(n, 31) + b) >>> 0;
  return (n % 64).toString(16).padStart(2, '0');
}
export async function sha(text) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))), x => x.toString(16).padStart(2, '0')).join('');
}
export function affiliateOrigins(env) {
  return (env.MIDOKORO_AFFILIATE_ORIGINS || '').split(',').flatMap(value => {
    try {
      const u = new URL(value.trim());
      return u.protocol === 'https:' && !u.username && !u.password && !u.search && !u.hash && u.pathname === '/' ? [u.origin] : [];
    } catch { return []; }
  });
}
export function adsEnabled(request, env) {
  const origin = new URL(request.url).origin;
  const source = request.headers.get('Origin');
  return origin === (env.MIDOKORO_PUBLIC_ORIGIN || '').replace(/\/$/, '') && affiliateOrigins(env).includes(origin) && (!source || source === origin);
}
async function asset(env, name) {
  return env.ASSETS.fetch(new Request('https://assets.internal/' + name));
}
async function data(env, name) {
  const response = await asset(env, '_data/' + name);
  if (!response.ok) throw new APIError('Published snapshot unavailable', 503);
  return response.json();
}
async function item(env, kind, id) {
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(id)) return null;
  return (await data(env, `${kind}/items/${bucket(id)}.json`))[id] || null;
}
async function lookup(env, kind, key) {
  return (await data(env, `${kind}/cache/${key.slice(0, 2)}.json`))[key];
}
class APIError extends Error {
  constructor(message, status = 502) { super(message); this.status = status; }
}

// Only allow fixed upstreams. User input is always encoded as a query parameter.
async function upstream(host, params) {
  const url = new URL('/w/api.php', host);
  url.search = new URLSearchParams({format: 'json', ...params});
  for (let attempt = 0; attempt < 3; attempt++) {
    let response;
    try {
      response = await fetch(url, {headers: {'User-Agent': userAgent}, signal: AbortSignal.timeout(12000), cf: {cacheTtl: 0}});
    } catch {
      if (attempt < 2) { await sleep(500 * 2 ** attempt); continue; }
      throw new APIError('Upstream temporarily unavailable');
    }
    if (response.status === 429 || response.status >= 500) {
      if (attempt < 2) {
        const delay = Math.min(3000, Math.max(500 * 2 ** attempt, Number(response.headers.get('Retry-After') || 0) * 1000));
        await response.body?.cancel();
        await sleep(delay);
        continue;
      }
      throw new APIError('Upstream temporarily unavailable', 503);
    }
    if (!response.ok) throw new APIError('Upstream request failed', response.status === 404 ? 404 : 502);
    const result = await response.json();
    if (result.error) throw new APIError('Upstream API error', result.error.code === 'missingtitle' ? 404 : 502);
    return result;
  }
}
async function entity(qid) {
  if (!/^Q[1-9]\d*$/.test(qid)) throw new APIError('Invalid qid', 400);
  const result = await upstream('https://www.wikidata.org', {action: 'wbgetentities', ids: qid, props: 'claims|sitelinks'});
  const e = result.entities?.[qid];
  if (!e || 'missing' in e) throw new APIError('Wikidata item not found', 404);
  return e;
}
const claims = (e, p) => (e.claims?.[p] || []).filter(s => s.rank !== 'deprecated').map(s => s.mainsnak?.datavalue?.value).filter(v => v != null);
const stripHTML = text => String(text || '').replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").trim();
async function imageInfo(file) {
  if (!file) throw new APIError('Image not found', 404);
  file = file.replace(/^(File:|ファイル:)/, '');
  const result = await upstream('https://commons.wikimedia.org', {action: 'query', prop: 'imageinfo', titles: 'File:' + file, iiprop: 'url|mime|extmetadata', iiurlwidth: '1200'});
  const page = Object.values(result.query?.pages || {})[0];
  const info = page?.imageinfo?.[0];
  const meta = info?.extmetadata || {};
  const license = stripHTML(meta.LicenseShortName?.value || meta.License?.value);
  const url = info?.thumburl || info?.url || '';
  if (!license || !url.startsWith('https://') || !['image/jpeg', 'image/png', 'image/webp'].includes(info.mime?.toLowerCase())) throw new APIError('No attributed image', 404);
  return {url, license, license_url: meta.LicenseUrl?.value || '', artist: stripHTML(meta.Artist?.value), credit: stripHTML(meta.Credit?.value), source_url: info.descriptionurl || 'https://commons.wikimedia.org/wiki/File:' + encodeURIComponent(file), attribution_required: meta.AttributionRequired?.value === 'true'};
}
async function wikidataImage(qid) { return imageInfo(claims(await entity(qid), 'P18')[0]); }
async function wikidataLinks(qid) {
  const e = await entity(qid);
  const result = {};
  const official = claims(e, 'P856')[0];
  if (official) result.official_site = official;
  for (const [p, key, base] of [['P2013', 'facebook', 'https://www.facebook.com/'], ['P2002', 'twitter', 'https://x.com/'], ['P2003', 'instagram', 'https://www.instagram.com/'], ['P2397', 'youtube', 'https://www.youtube.com/channel/']]) {
    const value = claims(e, p)[0];
    if (value) result[key] = base + value;
  }
  // An infobox website is the existing fallback when Wikidata has no P856.
  if (!official && e.sitelinks?.jawiki?.title) {
    const parsed = await upstream('https://ja.wikipedia.org', {action: 'parse', page: e.sitelinks.jawiki.title, prop: 'wikitext', formatversion: '2', redirects: '1'});
    const site = officialSite(parsed.parse?.wikitext || '');
    if (site) { result.official_site = site; result.official_site_source = articleURL(e.sitelinks.jawiki.title); }
  }
  return result;
}
export function officialSite(text) {
  const bracket = /\|\s*外部リンク\s*=\s*\[\s*(https?:\/\/[^\s\[\]\|]+)/.exec(text)?.[1];
  const plain = /\|\s*外部リンク\s*=\s*(https?:\/\/[^\s\|\n]+)/.exec(text)?.[1];
  const start = text.indexOf('外部リンク');
  const fallback = start < 0 ? '' : /https?:\/\/[^\s\[\]\|>]+/.exec(text.slice(start, start + 600))?.[0];
  for (const candidate of [bracket, plain, fallback]) {
    if (!candidate) continue;
    try {
      const host = new URL(candidate).hostname;
      if (!/(^|\.)(wikipedia|wikimedia|wikivoyage)\.org$/.test(host)) return candidate.replace(/[,;]+$/, '');
    } catch {}
  }
  return '';
}

export function extractBlocks(fullText, target, headings, limit) {
  const levels = new Map(headings.map(h => [h.line, Number(h.level)]));
  const blocks = [];
  let active = !target, heading = '', lines = [];
  const flush = () => { if (lines.length) blocks.push({heading, text: lines.join('\n\n')}); lines = []; };
  for (const raw of fullText.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    if (!active) { if (line === target.line) active = true; continue; }
    if (levels.has(line)) {
      if (!target || levels.get(line) <= Number(target.level)) break;
      flush(); heading = line;
    } else lines.push(line);
  }
  flush();
  const output = [];
  let budget = limit;
  for (const b of blocks) {
    const head = Array.from(b.heading), text = Array.from(b.text);
    if (budget <= 0) break;
    const cost = head.length + text.length;
    if (cost <= budget) { output.push(b); budget -= cost; }
    else { output.push({heading: head.slice(0, budget).join(''), text: text.slice(0, Math.max(0, budget - head.length - 1)).join('') + '…'}); break; }
  }
  return output;
}
async function article(title, qid, intro = false) {
  const result = await upstream('https://ja.wikipedia.org', {action: 'query', formatversion: '2', redirects: '1', prop: intro ? 'extracts|pageimages|pageprops|images' : 'extracts', explaintext: '1', exsectionformat: 'plain', titles: title, ...(intro ? {exintro: '1', exchars: '700', piprop: 'thumbnail|name', pithumbsize: '1200', pilicense: 'free', imlimit: '20'} : {})});
  const page = result.query?.pages?.[0];
  if (!page || page.missing || !page.extract?.trim() || (intro && page.pageprops?.wikibase_item !== qid)) throw new APIError('Wikipedia article content not found', 404);
  return page;
}
async function panel(env, kind, title, customSpecs) {
  const page = await article(title);
  const result = await upstream('https://ja.wikipedia.org', {action: 'parse', page: title, prop: 'sections'});
  if (!result.parse || !Array.isArray(result.parse.sections)) throw new APIError('Wikipedia sections unavailable');
  const headings = result.parse.sections.map(h => ({line: stripHTML(h.line), level: Number(h.level)}));
  const specs = customSpecs || (await data(env, 'specs.json'))[kind];
  const headingKey = await sha('headingmap|' + (kind === 'geo' ? 'geo-v1|' : '') + title + '|' + headings.map(h => h.line).sort().join('\n'));
  let headingMap = {};
  const stored = await lookup(env, kind, headingKey);
  if (stored) { try { headingMap = JSON.parse(stored); } catch {} }
  const sections = {};
  let retry = false;
  for (const spec of specs) {
    const target = spec.candidates.map(line => headings.find(h => h.line === line)).find(Boolean) || headings.find(h => h.line === headingMap[spec.key]);
    const blocks = (!spec.candidates.length || target) ? extractBlocks(page.extract, target, headings, summaryKeyed(kind) ? 600 : 2000) : [];
    const section = {};
    if (blocks.length || kind === 'tokusan') {
      const suffix = summaryKeyed(kind) ? '|' + page.extract : '';
      const version = kind === 'tokusan' ? ' v1' : summaryKeyed(kind) ? '' : ' v3';
      const cached = await lookup(env, kind, await sha(title + '|' + spec.label + version + suffix));
      if (cached && cached !== 'なし') {
        if (summaryKeyed(kind)) section.summary = cached;
        else {
          let value;
          try { value = JSON.parse(cached); } catch { value = {summary: cached}; }
          if (value.summary && value.summary !== 'なし') section.summary = value.summary;
          if (Array.isArray(value.items) && value.items.length) section.items = value.items;
        }
      } else if (!cached && kind === 'tokusan') retry = true;
      if (blocks.length) section.blocks = blocks;
      if (Object.keys(section).length) section.source_url = articleURL(kind === 'tokusan' ? page.title : title);
    }
    sections[spec.key] = section;
  }
  return {sections, retry};
}
async function municipalityTitle(qid) {
  const types = new Set(['Q494721', 'Q1059478', 'Q4174776', 'Q5327704', 'Q1137833', 'Q1145012', 'Q1749269']);
  const queue = [[qid, 0]], seen = new Set();
  while (queue.length) {
    const [id, depth] = queue.shift();
    if (seen.has(id)) continue;
    seen.add(id);
    const e = await entity(id);
    if (id !== qid && claims(e, 'P31').some(v => types.has(v.id)) && e.sitelinks?.jawiki?.title) return e.sitelinks.jawiki.title;
    if (depth < 3) for (const v of claims(e, 'P131')) if (v.id) queue.push([v.id, depth + 1]);
    if (seen.size > 12) break;
  }
  return '';
}
async function wikipediaContent(env, kind, title, qid) {
  const page = await article(title, qid, true);
  const response = {description: page.extract.trim(), source_url: articleURL(page.title), content_license_url: 'https://creativecommons.org/licenses/by-sa/4.0/'};
  const candidates = [...new Set([page.pageimage, ...(page.images || []).map(i => i.title)].filter(file => file && !/logo|icon|wiki letter|camera-photo|\.svg$/i.test(file)))];
  for (const file of candidates) {
    try {
      const photo = await imageInfo(file);
      Object.assign(response, {image_url: photo.url, license: photo.license, license_url: photo.license_url, artist: photo.artist, credit: photo.credit, image_source_url: photo.source_url});
      break;
    } catch (e) { if (e.status !== 404) break; }
  }
  try {
    const {sections} = await panel(env, kind, title);
    if (kind === 'onsen' && (!sections.food?.items?.length || !sections.tourism?.items?.length)) {
      try {
        const muni = await municipalityTitle(qid);
        if (muni) {
          const all = (await data(env, 'specs.json')).onsen;
          const specs = [{...all.find(s => s.key === 'food'), candidates: ['名産・特産', '名物・特産品', '名産品・特産品', '特産・名産', '特産品', '名産品', '名産', '特産', '名物', '郷土料理', 'グルメ・特産品', '郷土料理・ご当地グルメ', '文化・名物']}, {...all.find(s => s.key === 'tourism'), candidates: ['観光スポット', '名所・旧跡・観光スポット', '名所・旧跡', '名所・旧跡・観光地', '観光地', '名所・旧跡・観光スポット・祭事・催事', '観光地・祭事・催事', '観光']}];
          const fallback = (await panel(env, kind, muni, specs)).sections;
          for (const key of ['food', 'tourism']) if (!sections[key]?.items?.length && fallback[key]?.items?.length) sections[key] = {...fallback[key], source_title: muni};
        }
      } catch (e) { if (e.status !== 404) response.sections_unavailable = true; }
    }
    const row = kind === 'shiseki' ? await item(env, kind, qid) : null;
    for (const [index, [key, section]] of Object.entries(sections).entries()) {
      if (kind !== 'shiseki' || ['special', 'national', 'local'].includes(row?.designation)) {
        if (summaryKeyed(kind) && !section.summary && section.blocks?.length) section.raw_omitted = true;
        delete section.blocks;
      }
      response[kind === 'geo' ? geoSlots[index] : key] = section;
    }
  } catch (e) { if (e.status !== 404) response.sections_unavailable = true; }
  return response;
}

export function hotelLink(request, env, kind) {
  const p = new URL(request.url).searchParams;
  if (!p.get('prefecture')) return error('prefecture parameter is required', 400);
  const names = ['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','栃木県','群馬県','茨城県','埼玉県','千葉県','東京都','神奈川県','山梨県','長野県','新潟県','富山県','石川県','福井県','静岡県','岐阜県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県'];
  const lrg = p.get('lrg_code') || '', sml = p.get('sml_code') || '';
  let prefecture = p.get('prefecture');
  if (prefecture === '２県以上' && /^\d{4}00$/.test(lrg)) prefecture = names[Number(lrg.slice(0, 2)) - 1] || prefecture;
  const index = names.indexOf(prefecture);
  if (index < 0) return error('unknown prefecture', 400);
  const code = String(index + 1).padStart(2, '0');
  const large = /^\d{4}00$/.test(lrg) && lrg.startsWith(code);
  const small = /^\d{6}$/.test(sml) && sml.startsWith(lrg.slice(0, 4)) && !sml.endsWith('00');
  let destination = `https://www.jalan.net/${code}0000/`, label = prefecture;
  if (large) { destination += `LRG_${lrg}/`; label = p.get('lrg_name') || label; if (small) { destination += `SML_${sml}/`; label = p.get('sml_name') || label; } }
  const tracking = adsEnabled(request, env) ? env[`MIDOKORO_${kind.toUpperCase()}_A8MAT`] || env.JALAN_A8MAT : '';
  if (tracking) destination = 'https://px.a8.net/svt/ejp?' + new URLSearchParams({a8ejpredirect: destination, a8mat: tracking});
  return json({hotels: [{name: `${label}の宿を探す（じゃらん）`, detail_url: destination}]}, 200, {'Cache-Control': 'private, no-store'});
}

// A single globally named object coordinates the public Nominatim limit.
// Only the next permitted timestamp is persisted; no coordinates or identifiers.
export class GeocodingGate {
  constructor(state) { this.state = state; this.queue = Promise.resolve(); this.waiting = 0; }
  async fetch(request) {
    if (this.waiting >= 10) return error('Geocoding busy; retry shortly', 429);
    this.waiting++;
    const result = this.queue.then(async () => {
      const next = (await this.state.storage.get('next')) || 0;
      await sleep(Math.max(0, next - Date.now()));
      // Reserve immediately before the actual outbound request. Worker scheduling
      // cannot compress the spacing between requests in different edge regions.
      await this.state.storage.put('next', Date.now() + 1100);
      const {lat, lng} = await request.json();
      const url = new URL('https://nominatim.openstreetmap.org/reverse');
      url.search = new URLSearchParams({format: 'json', lat: lat.toFixed(6), lon: lng.toFixed(6), addressdetails: '1', zoom: '16'});
      try {
        const response = await fetch(url, {headers: {'User-Agent': userAgent}, signal: AbortSignal.timeout(10000)});
        if (!response.ok) return json({success: false, error_message: 'Address lookup temporarily unavailable'}, 503);
        return json(await response.json());
      } catch { return json({success: false, error_message: 'Address lookup temporarily unavailable'}, 503); }
    });
    this.queue = result.then(() => {}, () => {});
    try { return await result; } finally { this.waiting--; }
  }
}
async function reverseGeocode(request, env) {
  if (Number(request.headers.get('Content-Length') || 0) > 1024) return error('Request body too large', 413);
  let body;
  try { const text = await request.text(); if (text.length > 1024) return error('Request body too large', 413); body = JSON.parse(text); } catch { return error('Invalid request body', 400); }
  const {lat, lng} = body;
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return error('Invalid coordinates', 400);
  const key = new Request(`https://midokoro-geocoding.internal/${lat.toFixed(6)}/${lng.toFixed(6)}`);
  const cache = globalThis.caches?.default;
  let result = cache ? await cache.match(key) : null;
  if (!result) {
    const gate = env.GEOCODING_GATE.get(env.GEOCODING_GATE.idFromName('nominatim-global'));
    result = await gate.fetch(new Request('https://gate.internal/reverse', {method: 'POST', body: JSON.stringify({lat, lng})}));
    if (!result.ok) return result;
    if (cache) {
      const cached = new Response(result.clone().body, {headers: {'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=86400'}});
      await cache.put(key, cached);
    }
  }
  const a = (await result.json()).address || {};
  const location = a.city || a.town || a.village || a.suburb || '';
  return json({success: true, location, full_location: [...new Set([a.state, location, a.city_district, a.suburb, a.quarter, a.neighbourhood, a.road].filter(Boolean))].join(' '), prefecture: a.state || '', city: location, error_message: ''});
}

async function route(request, env) {
  const url = new URL(request.url), path = url.pathname;
  if (path.startsWith('/_data/')) return error('Not found', 404);
  if (path === '/health') return json({status: 'ok', service: 'midokoro-map'});
  if (path === '/api/config') {
    if (request.method !== 'GET') return error('Method not allowed', 405);
    return json({defaultKind: env.MIDOKORO_DEFAULT_KIND || 'shiseki', affiliateOrigins: affiliateOrigins(env), summariesOnly: false});
  }
  if (path.startsWith('/api/story-events/')) {
    if (request.method !== 'POST') return error('Method not allowed', 405);
    const parts = path.split('/');
    if (parts.length !== 5 || !slugs.includes(parts[3]) || !events.includes(parts[4]) || url.search) return error('Not found', 404);
    const site = request.headers.get('Sec-Fetch-Site');
    if (site && site !== 'same-origin') return error('same origin required', 403);
    if ((await request.text()).length) return error('empty body required', 400);
    console.log(`story_event story=${parts[3]} event=${parts[4]}`);
    return new Response(null, {status: 204, headers: {'Cache-Control': 'no-store'}});
  }
  const geo = /^\/api\/geo\/wiki\/(image|content)$/.exec(path);
  if (geo) {
    if (request.method !== 'GET') return error('Method not allowed', 405);
    const p = url.searchParams, qid = p.get('qid') || '';
    if (geo[1] === 'image') return json(await wikidataImage(qid));
    const title = p.get('title');
    if (!title || !qid || title.length > 300) return error('title and qid parameters are required', 400);
    return json(await wikipediaContent(env, 'geo', title, qid));
  }
  const match = /^\/api\/([^/]+)\/(.*)$/.exec(path);
  if (!match || !kinds.includes(match[1])) return error('Not found', 404);
  const kind = match[1], endpoint = match[2], p = url.searchParams;
  if (endpoint === 'geocoding/reverse' && kind !== 'tokusan') return request.method === 'POST' ? reverseGeocode(request, env) : error('Method not allowed', 405);
  if (request.method !== 'GET') return error('Method not allowed', 405);
  const collection = collections[kind];
  if (endpoint === collection || endpoint === collection + '/' || endpoint === collection + '/descriptions') {
    const response = await asset(env, `_data/${kind}/list.json`);
    return new Response(response.body, {status: response.status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-cache'}});
  }
  if (endpoint.startsWith(collection + '/prefecture/')) {
    const prefecture = decodeURIComponent(endpoint.slice((collection + '/prefecture/').length)).trim();
    if (!prefecture) return error('Prefecture parameter is required', 400);
    const response = await asset(env, `_data/${kind}/prefectures/${await sha(prefecture)}.json`);
    if (response.status === 404) return json([]);
    return new Response(response.body, {status: response.status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-cache'}});
  }
  if (endpoint.startsWith(collection + '/')) {
    // The existing onsen router serves its full list for this prefix; it does
    // not register an item-by-QID handler. Preserve that public contract.
    if (kind === 'onsen') {
      const response = await asset(env, `_data/${kind}/list.json`);
      return new Response(response.body, {status: response.status, headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-cache'}});
    }
    const row = await item(env, kind, endpoint.slice(collection.length + 1));
    return row ? json(row) : error('Not found', 404);
  }
  if (endpoint === 'hotel-area/nearby' && kind !== 'tokusan') return hotelLink(request, env, kind);
  if (endpoint === 'jalan/nearby' && kind === 'shiseki') return error('Jalan Web Service unavailable', 503);
  if (endpoint === 'wiki/image' || (kind === 'tokusan' && endpoint === 'wikiimage')) return json(await wikidataImage(p.get('qid') || ''));
  if (endpoint === 'wiki/links' && kind !== 'tokusan') return json(await wikidataLinks(p.get('qid') || ''));
  if (endpoint === 'wiki/content' && kind !== 'tokusan') {
    const title = p.get('title'), qid = p.get('qid');
    if (!title || !qid || title.length > 300) return error('title and qid parameters are required', 400);
    return json(await wikipediaContent(env, kind, title, qid));
  }
  if (endpoint.startsWith('sections/') && kind === 'tokusan') {
    const id = endpoint.slice(9), row = await item(env, kind, id);
    if (!row) return error('Tokusan not found', 404);
    if (row.description) return json((await data(env, `${kind}/items/${bucket(id)}.json`))['sections:' + id]);
    const source = row.source_url || '';
    if (!source.startsWith('https://ja.wikipedia.org/wiki/')) return json({sections: {}});
    const title = decodeURIComponent(source.slice('https://ja.wikipedia.org/wiki/'.length)).replaceAll('_', ' ');
    try { const result = await panel(env, kind, title); return json({sections: result.sections, ...(result.retry ? {sections_retry: true} : {})}); }
    catch (e) { return json({sections: {}, ...(e.status !== 404 ? {sections_unavailable: true} : {})}); }
  }
  if (endpoint === 'commons/image' && kind === 'omatsuri') {
    const label = p.get('label')?.trim(), prefecture = p.get('prefecture')?.trim() || '';
    if (!label || label.length > 300 || prefecture.length > 100) return error('label parameter is required', 400);
    const result = await upstream('https://commons.wikimedia.org', {action: 'query', formatversion: '2', generator: 'search', gsrsearch: label + (prefecture ? ' ' + prefecture : ''), gsrnamespace: '6', gsrlimit: '50', gsrsort: 'relevance', prop: 'info', inprop: 'url'});
    const pages = result.query?.generatorpages || result.query?.pages || [];
    let tried = 0;
    const seen = new Set();
    for (const page of Object.values(pages)) {
      const file = page.title?.replace(/^(File:|ファイル:)/, '');
      if (!file || file.replace(/\.(jpe?g|png|svg|gif|webp)$/i, '') !== label || seen.has(file)) continue;
      seen.add(file);
      try {
        const photo = await imageInfo(file);
        return json({image_url: photo.url, license: photo.license, license_url: photo.license_url, artist: photo.artist, credit: photo.credit, image_source_url: photo.source_url, attribution_required: photo.attribution_required});
      } catch (e) { if (++tried >= 3) break; }
    }
    return error('no licensed image found', 404);
  }
  return error('Not found', 404);
}

export default {
  async fetch(request, env) {
    try {
      // A cold Wikipedia parse can exceed the Free Worker's 10ms CPU budget.
      // SQLite-backed Durable Objects are available on Free and provide the
      // CPU budget needed for the existing article/attribution processing.
      const path = new URL(request.url).pathname;
      if (request.method === 'GET' && /^\/api\/(shiseki|onsen|omatsuri|tokusan|geo)\/(wiki\/(content|image|links)|wikiimage|commons\/image|sections\/)/.test(path) && env.EXTERNAL_API) {
        const shard = await sha(request.url);
        return await env.EXTERNAL_API.get(env.EXTERNAL_API.idFromName(shard)).fetch(request);
      }
      return await route(request, env);
    }
    catch (e) { return error(e instanceof APIError ? e.message : 'Request temporarily unavailable', e.status || 503); }
  }
};

// No article, request, coordinate or visitor state is persisted by this object.
// Each URL is isolated so an upstream wait cannot block another item's panel.
export class ExternalAPI {
  constructor(state, env) { this.env = env; }
  async fetch(request) {
    try { return await route(request, this.env); }
    catch (e) { return error(e instanceof APIError ? e.message : 'Request temporarily unavailable', e.status || 503); }
  }
}
