// Protected, temporary CPU-accounting experiment. No provider HTTP or DB.
import localWorker, {forwardWire} from './worker.mjs';
import sourceDigest, {wrapperDigest} from './_digest.mjs';
let runtimeId, invocation = 0;
export default {
  async fetch(request, env) {
    const sequence = ++invocation;
    if (!env.IKIMONO_PREVIEW_PASSWORD) return new Response('Unavailable', {status: 503});
    const supplied = request.headers.get('Authorization') || '';
    const expected = 'Basic ' + new TextEncoder().encode('preview:' + env.IKIMONO_PREVIEW_PASSWORD).toBase64();
    let difference = supplied.length ^ expected.length;
    for (let i = 0; i < expected.length; i++) difference |= (supplied.charCodeAt(i) || 0) ^ expected.charCodeAt(i);
    if (difference) return new Response('Authentication required', {status: 401,
      headers: {'WWW-Authenticate': 'Basic realm="transport CPU experiment"', 'Cache-Control': 'no-store'}});
    const url = new URL(request.url);
    if (url.hostname !== 'ikimono-note-transport-preview.ats030.workers.dev') return new Response('Invalid host', {status: 400});
    // Only transport/health measurements, no checked payload reflection route.
    const routes = {'/health': '/health', '/payload/1': '/payload', '/payload/3': '/payload', '/wire/1': '/wire', '/wire/3': '/wire'};
    if (!Object.hasOwn(routes, url.pathname)) return new Response('Not found', {status: 404});
    url.pathname = routes[url.pathname];
    url.hostname = 'localhost';
    let response;
    if (url.pathname === '/wire') {
      // The local development bridge needs an identity TransformStream to
      // avoid reusing a consumed body. Measure the native production stream
      // separately, using the original request rather than making a copy.
      response = forwardWire(request, false);
    } else {
      const forwarded = new Request(url, request);
      forwarded.headers.set('host', 'localhost');
      response = await localWorker.fetch(forwarded);
    }
    response.headers.set('Cache-Control', 'no-store'); response.headers.set('X-Robots-Tag', 'noindex, nofollow');
    response.headers.set('X-Transport-Source-SHA256', sourceDigest);
    response.headers.set('X-Transport-Wrapper-SHA256', wrapperDigest);
    const marker = request.headers.get('X-Ikimono-CPU-Probe') || '';
    if (/^[0-9a-f]{8}$/.test(marker)) {
      runtimeId ||= crypto.randomUUID();
      response.headers.set('X-Preview-Isolate', runtimeId);
      response.headers.set('X-Preview-Isolate-Invocation', String(sequence));
    }
    return response;
  }
};
