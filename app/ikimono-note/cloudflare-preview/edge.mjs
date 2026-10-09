// Same protected preview URL; Python owns all routes except session status.
import {readSession} from '../worker_session.mjs';
import {bundleDigest, pythonBundleDigest, securityHeaders} from './_edge_policy.mjs';
let isolateId, invocation = 0;
function sessionCookie(header) {
  let result;
  for (const item of (header || '').split(';')) {
    const index = item.indexOf('=');
    if (index < 0 || item.slice(0, index).trim() !== 'ikimono_session') continue;
    let value = item.slice(index + 1).trim();
    if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1).replace(/\\([0-3][0-7][0-7]|.)/g,
      (_, escaped) => escaped.length === 3 ? String.fromCharCode(parseInt(escaped, 8)) : escaped);
    result = value;
  }
  return result;
}
export default {
  async fetch(request, env) {
    const sequence = ++invocation;
    const headers = {'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow'};
    const reject = (text, status, extra = {}) => new Response(text, {status, headers: {...headers, ...extra}});
    if (!env.IKIMONO_PREVIEW_PASSWORD?.trim() || !env.IKIMONO_SESSION_SECRET?.trim()) return reject('Unavailable', 503);
    const expected = 'Basic ' + btoa(String.fromCharCode(...new TextEncoder().encode('preview:' + env.IKIMONO_PREVIEW_PASSWORD)));
    const supplied = request.headers.get('Authorization') || '';
    let difference = supplied.length ^ expected.length;
    for (let i = 0; i < expected.length; i++) difference |= (supplied.charCodeAt(i) || 0) ^ expected.charCodeAt(i);
    if (difference) return reject('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="ikimono-note preview", charset="UTF-8"'});
    if (!env.DB || !env.PYTHON) return reject('Database or backend unavailable', 503);
    const url = new URL(request.url);
    const host = (request.headers.get('Host') || url.host).split(':')[0];
    if (!(env.IKIMONO_ALLOWED_HOSTS || '').split(',').map(s => s.trim()).includes(host) ||
        !(env.IKIMONO_ALLOWED_HOSTS || '').split(',').map(s => s.trim()).includes(url.hostname)) return reject('Invalid host header', 400);
    let path;
    try {path = decodeURIComponent(url.pathname);} catch {return reject('Invalid path', 400);}
    if (path.startsWith('/probe/')) return reject('Not found', 404);
    let response;
    if (path === '/api/me' && env.IKIMONO_JS_SESSION === '1') {
      if (request.method !== 'GET') response = new Response('Method not allowed', {status: 405, headers: {Allow: 'GET'}});
      else {
        const names = ['IKIMONO_GOOGLE_CLIENT_ID', 'IKIMONO_GOOGLE_CLIENT_SECRET', 'IKIMONO_PUBLIC_ORIGIN'];
        const missing = names.find(name => {
          const value = String(env[name] || '').trim();
          return !(name === 'IKIMONO_PUBLIC_ORIGIN' ? value.replace(/\/+$/, '') : value);
        });
        const session = await readSession(sessionCookie(request.headers.get('Cookie')), env.IKIMONO_SESSION_SECRET.trim());
        response = Response.json({available: !missing, reason: missing ? missing + ' が未設定です' : '',
          signed_in: !!session, email: session?.email ?? null});
      }
      for (const [name, value] of Object.entries(securityHeaders)) response.headers.set(name, value);
    } else {
      // Preserve URL/origin, headers, repeated Set-Cookie, body and redirect.
      const original = await env.PYTHON.fetch(request);
      if (path === '/health' && original.headers.get('X-Preview-Bundle-SHA256') !== pythonBundleDigest) {
        await original.body?.cancel();
        return reject('Backend release mismatch', 503);
      }
      response = new Response(original.body, original);
      if (path === '/health') response.headers.set('X-Preview-Backend-Bundle-SHA256', pythonBundleDigest);
    }
    for (const [name, value] of Object.entries(headers)) response.headers.set(name, value);
    // Runtime observations are owned by the outer entrypoint for every route.
    response.headers.delete('X-Preview-Isolate'); response.headers.delete('X-Preview-Isolate-Invocation');
    if (/^[0-9a-f]{8}$/.test(request.headers.get('X-Ikimono-CPU-Probe') || '')) {
      isolateId ||= crypto.randomUUID();
      response.headers.set('X-Preview-Isolate', isolateId);
      response.headers.set('X-Preview-Isolate-Invocation', String(sequence));
    }
    response.headers.set('X-Preview-Bundle-SHA256', bundleDigest);
    return response;
  }
};
