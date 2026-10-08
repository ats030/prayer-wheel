// Local synthetic serialization only: no outbound fetch, secrets, DB or AI.
import sourceDigest from './_digest.mjs';
const MAX_BODY = 6 * 1024 * 1024 + 16384;
const encoder = new TextEncoder();
export function forwardWire(request, transform = true) {
  // Transfer cost only; excludes model/input/auth validation and external HTTP.
  if (request.method !== 'POST') return new Response('Method not allowed', {status: 405});
  const length = request.headers.get('content-length') || '';
  if (!/^\d+$/.test(length) || Number(length) > 9 * 1024 * 1024) return new Response('Invalid length', {status: 400});
  if (request.headers.get('content-type') !== 'application/json') return new Response('Invalid type', {status: 415});
  const stream = transform ? request.body.pipeThrough(new TransformStream()) : request.body;
  return new Response(stream, {headers: {'content-type': 'application/json', 'X-Probe-Network-Calls': '0'}});
}
async function sha256(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
                    b => b.toString(16).padStart(2, '0')).join('');
}
export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (!['localhost', '127.0.0.1'].includes(url.hostname)
        || !['localhost', '127.0.0.1'].includes((request.headers.get('host') || '').split(':')[0])) {
      return new Response('Local synthetic probe only', {status: 403});
    }
    if (url.pathname === '/health' && request.method === 'GET') {
      return Response.json({synthetic: true, network_calls: 0, source_sha256: sourceDigest});
    }
    if (url.pathname === '/wire') {
      // Isolate unchanged byte forwarding only, not validation or auth. Never
      // use this echo handler as a production API proxy.
      return forwardWire(request);
    }
    if (!['/payload', '/payload-checked'].includes(url.pathname)) return new Response('Not found', {status: 404});
    if (request.method !== 'POST') return new Response('Method not allowed', {status: 405});
    const length = request.headers.get('content-length') || '';
    if (!/^\d+$/.test(length) || Number(length) > MAX_BODY) return new Response('Invalid length', {status: 400});
    let form;
    try { form = await request.formData(); } catch { return new Response('Invalid form', {status: 400}); }
    if ([...form.keys()].some(key => !['files', 'template'].includes(key))) return new Response('Invalid field', {status: 400});
    const files = form.getAll('files'), template = form.getAll('template');
    if (files.length < 1 || files.length > 3 || files.some(file => typeof file === 'string' || file.size > 2 * 1024 * 1024)
        || template.length !== 1 || typeof template[0] !== 'string' || template[0].length > 8192) {
      return new Response('Invalid synthetic inputs', {status: 400});
    }
    let payload;
    try {
      payload = JSON.parse(template[0]);
      const parts = payload.contents[0].parts;
      if (parts.length !== 2 || parts[0].inline_data.data !== '' || parts[0].inline_data.mime_type !== 'image/jpeg'
          || typeof parts[1].text !== 'string') throw new Error('Invalid template');
    } catch { return new Response('Invalid template', {status: 400}); }
    const photos = [], hashes = [];
    for (const file of files) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      photos.push({inline_data: {mime_type: 'image/jpeg', data: bytes.toBase64()}});
      hashes.push(await sha256(bytes));
    }
    payload.contents[0].parts = [...photos, payload.contents[0].parts[1]];
    const wire = encoder.encode(JSON.stringify(payload));
    const result = {probe: {sha256: hashes}, wire_bytes: wire.length, wire_sha256: await sha256(wire), network_calls: 0};
    if (url.pathname === '/payload-checked') result.payload = payload;
    return Response.json(result);
  }
};
