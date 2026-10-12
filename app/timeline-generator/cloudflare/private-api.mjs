// Owner-only Access verification and fixed VPC bridge. No dependency or new datastore.
let keyCache;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", {fatal: true});

function decode(value) {
  if (!value || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Invalid JWT");
  return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
}
function object(value) {
  const data = JSON.parse(decoder.decode(decode(value)));
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid JWT");
  return data;
}
export async function readLimited(body, limit) {
  if (!body) return new Uint8Array();
  const reader = body.getReader(), chunks = [];
  let size = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) { await reader.cancel(); throw new Error("Body too large"); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return bytes;
}
export function configured(env) {
  return env.PRIVATE_API && /^https:\/\/[a-z0-9][a-z0-9-]*\.cloudflareaccess\.com$/.test(env.ACCESS_ISSUER || "") &&
    /^[a-f0-9]{64}$/.test(env.ACCESS_AUD || "") &&
    typeof env.OWNER_EMAIL === "string" && /^[^\s@]+@[^\s@]+$/.test(env.OWNER_EMAIL) &&
    /^[A-Za-z0-9_-]{43,128}$/.test(env.GATEWAY_TOKEN || "");
}
export async function verifyOwner(request, env, getKeys = fetch) {
  if (!configured(env)) return false;
  try {
    const token = request.headers.get("Cf-Access-Jwt-Assertion");
    if (!token || token.length > 8192) return false;
    const parts = token.split(".");
    if (parts.length !== 3) return false;
    const header = object(parts[0]), claims = object(parts[1]);
    const now = Math.floor(Date.now() / 1000);
    if (header.alg !== "RS256" || typeof header.kid !== "string" || header.kid.length > 128 || header.crit ||
        (header.typ !== undefined && header.typ !== "JWT") || claims.iss !== env.ACCESS_ISSUER ||
        !Array.isArray(claims.aud) || !claims.aud.includes(env.ACCESS_AUD) ||
        !Number.isInteger(claims.exp) || claims.exp <= now ||
        !Number.isInteger(claims.iat) || claims.iat > now + 30 || claims.iat >= claims.exp ||
        (claims.nbf !== undefined && (!Number.isInteger(claims.nbf) || claims.nbf > now)) ||
        typeof claims.sub !== "string" || !claims.sub || claims.type !== "app" ||
        claims.email !== env.OWNER_EMAIL) return false;
    // Only a fixed, configured Cloudflare issuer supplies keys. Token jku/x5u URLs are ignored.
    if (!keyCache || keyCache.issuer !== env.ACCESS_ISSUER || keyCache.until <= now) {
      const response = await getKeys(env.ACCESS_ISSUER + "/cdn-cgi/access/certs", {
        redirect: "error", signal: AbortSignal.timeout(3000)
      });
      if (!response.ok) return false;
      const keys = JSON.parse(decoder.decode(await readLimited(response.body, 65536))).keys;
      if (!Array.isArray(keys) || keys.length > 16) return false;
      keyCache = {issuer: env.ACCESS_ISSUER, keys, until: now + 60};
    }
    const jwk = keyCache.keys.find(key => key.kid === header.kid && key.kty === "RSA" &&
      (!key.use || key.use === "sig") && (!key.alg || key.alg === "RS256"));
    if (!jwk || decode(jwk.n).length < 256) return false;
    const key = await crypto.subtle.importKey("jwk", jwk, {name: "RSASSA-PKCS1-v1_5", hash: "SHA-256"}, false, ["verify"]);
    return await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, decode(parts[2]), encoder.encode(parts[0] + "." + parts[1]));
  } catch { return false; }
}
export function allowedRoute(method, path, search) {
  if (search && !(method === "GET" && path === "/api/jobs" && /^\?offset=\d{1,18}$/.test(search))) return false;
  if (method === "GET") return ["/api/jobs", "/api/quality", "/api/health"].includes(path) || /^\/api\/jobs\/[1-9]\d{0,17}$/.test(path);
  return method === "POST" && (path === "/api/jobs" || /^\/api\/jobs\/[1-9]\d{0,17}\/(retry|regenerate|cancel|delete|milestones)$/.test(path));
}
function reply(status, error) {
  return Response.json({error}, {status, headers: privateHeaders});
}
const privateHeaders = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'", "Referrer-Policy": "no-referrer"};
export async function privateApi(request, env) {
  if (!configured(env)) return reply(503, "本人用の生成接続は準備中です。");
  if (!await verifyOwner(request, env)) return reply(403, "本人認証が必要です。");
  const url = new URL(request.url), path = url.pathname.replace(/^\/api\/private\//, "/api/");
  if (!allowedRoute(request.method, path, url.search)) return reply(404, "APIが見つかりません。");
  if (request.method === "POST" && (request.headers.get("Origin") !== url.origin ||
      request.headers.get("Content-Type")?.split(";")[0] !== "application/json")) {
    return reply(403, "同じ画面からJSON形式で操作してください。");
  }
  let body;
  if (request.method === "POST") {
    try { body = await readLimited(request.body, path.endsWith("/milestones") ? 65536 : 2048); }
    catch { return reply(413, "入力サイズが上限外か、読み取れませんでした。"); }
  }
  try {
    const response = await env.PRIVATE_API.fetch("http://127.0.0.1:8535" + path + url.search, {
      method: request.method, body, redirect: "error", signal: AbortSignal.timeout(12000),
      headers: {"Authorization": "Bearer " + env.GATEWAY_TOKEN, "Content-Type": "application/json"}
    });
    if (response.status >= 300 && response.status < 400 || !response.headers.get("Content-Type")?.startsWith("application/json")) {
      throw new Error("Unexpected bridge response");
    }
    const data = JSON.parse(decoder.decode(await readLimited(response.body, 4 * 1024 * 1024)));
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid response");
    if (data.result && typeof data.result === "object") delete data.result.trace;
    return Response.json(data, {status: response.status, headers: privateHeaders});
  } catch { return reply(502, "生成処理へ接続できませんでした。"); }
}
