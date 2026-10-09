// Existing auth.py session format. No OAuth, database or cookie issuance here.
const encoder = new TextEncoder();
export async function readSession(cookie, secret, now = Date.now() / 1000) {
  if (!secret || typeof cookie !== 'string' || cookie.length > 4096) return null;
  const dot = cookie.indexOf('.');
  if (dot < 1) return null;
  const body = cookie.slice(0, dot), signature = cookie.slice(dot + 1);
  if (!/^[A-Za-z0-9_-]{43}$/.test(signature)) return null;
  try {
    const decode = text => Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - text.length % 4) % 4)), c => c.charCodeAt(0));
    const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['verify']);
    // Reject noncanonical signature encodings just as Python's string comparison does.
    const signed = decode(signature);
    const canonical = btoa(String.fromCharCode(...signed)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    if (canonical !== signature || !await crypto.subtle.verify('HMAC', key, signed, encoder.encode(body))) return null;
    const payload = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(decode(body)));
    if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
        typeof payload.exp !== 'number' || !Number.isFinite(payload.exp) || payload.exp < now) return null;
    return payload;
  } catch {return null;}
}

export async function sessionStatus(cookie, secret, configured) {
  const session = await readSession(cookie, secret);
  return {available: configured, reason: configured ? '' : 'IKIMONO_GOOGLE_CLIENT_ID が未設定です',
    signed_in: !!session, email: session?.email ?? null};
}
