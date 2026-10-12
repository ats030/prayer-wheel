import assert from "node:assert/strict";
import {allowedRoute, configured, privateApi, readLimited, verifyOwner} from "./private-api.mjs";
import app from "./app-worker.mjs";

const pair = await crypto.subtle.generateKey({name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256"}, true, ["sign", "verify"]);
const jwk = {...await crypto.subtle.exportKey("jwk", pair.publicKey), kid: "test-key", use: "sig", alg: "RS256"};
const env = {ACCESS_ISSUER: "https://timeline-test.cloudflareaccess.com", ACCESS_AUD: "a".repeat(64),
  OWNER_EMAIL: "owner@example.com", GATEWAY_TOKEN: "t".repeat(43), PRIVATE_API: {}};
const now = Math.floor(Date.now() / 1000);
const claims = {iss: env.ACCESS_ISSUER, aud: [env.ACCESS_AUD], email: env.OWNER_EMAIL,
  sub: "test-owner", type: "app", iat: now - 10, exp: now + 60};
const b64 = value => Buffer.from(typeof value === "string" ? value : JSON.stringify(value)).toString("base64url");
async function token(overrides = {}, header = {}) {
  const message = b64({alg: "RS256", kid: jwk.kid, typ: "JWT", ...header}) + "." + b64({...claims, ...overrides});
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", pair.privateKey, Buffer.from(message));
  return message + "." + Buffer.from(signature).toString("base64url");
}
let certRequests = 0;
async function keys(url, options) {
  certRequests++;
  assert.equal(url, env.ACCESS_ISSUER + "/cdn-cgi/access/certs");
  assert.equal(options.redirect, "error");
  return Response.json({keys: [jwk]});
}
const valid = await token();
const request = (value = valid, method = "GET", path = "/api/private/jobs", extras = {}) => new Request(
  "https://timeline-generator.ats030.workers.dev" + path, {method, headers: {"Cf-Access-Jwt-Assertion": value, ...extras},
    ...(method === "POST" ? {body: JSON.stringify({query: "test"})} : {})});
assert.equal(configured({}), undefined);
assert.equal(await verifyOwner(request(), {}, keys), false);
assert.equal(await verifyOwner(new Request("https://example.org"), env, keys), false);
assert.equal(await verifyOwner(request(), env, keys), true);
for (const overrides of [{iss: "https://evil.example"}, {aud: ["b".repeat(64)]}, {email: "someone@example.com"},
  {exp: now - 1}, {exp: String(now + 60)}, {iat: now + 60}, {nbf: now + 30}, {sub: ""}, {type: "service"}]) {
  assert.equal(await verifyOwner(request(await token(overrides)), env, keys), false);
}
for (const header of [{alg: "none"}, {alg: "HS256"}, {kid: "unknown"}, {crit: ["unknown"]}]) {
  assert.equal(await verifyOwner(request(await token({}, header)), env, keys), false);
}
const forged = valid.split(".");
forged[1] = b64({...claims, exp: now + 500});
assert.equal(await verifyOwner(request(forged.join(".")), env, keys), false);
assert.equal(await verifyOwner(request(valid.slice(0, -20)), env, keys), false);
assert.equal(await verifyOwner(request(await token({}, {jku: "https://evil.example/keys"})), env, keys), true);
assert.equal(certRequests, 1); // Keys cache; token-provided URL is never fetched.
for (const path of ["/api/jobs/1/delete", "/data/private.sqlite3", "/api/jobs/../quality"]) {
  assert.equal(allowedRoute("GET", path, ""), false);
}
assert.equal(allowedRoute("GET", "/api/jobs", "?offset=1&url=https://evil.example"), false);
assert.equal(allowedRoute("POST", "/api/jobs/1/cancel", ""), true);
await assert.rejects(readLimited(new Response("x".repeat(2049)).body, 2048));
assert.equal((await privateApi(request(), {})).status, 503);
globalThis.fetch = keys;
let forwarded = [];
env.PRIVATE_API.fetch = async (url, options) => {
  forwarded.push({url, options});
  return Response.json({id: 1, result: {events: [], trace: {secret: "not forwarded"}}}, {status: 201});
};
assert.equal((await privateApi(request("invalid"), env)).status, 403);
assert.equal((await privateApi(request(valid, "POST"), env)).status, 403);
assert.equal((await privateApi(request(valid, "GET", "/api/private/jobs?url=https://evil.example"), env)).status, 404);
assert.equal(forwarded.length, 0);
const oversized = new Request("https://timeline-generator.ats030.workers.dev/api/private/jobs", {
  method: "POST", body: "x".repeat(2049), headers: {"Cf-Access-Jwt-Assertion": valid,
    Origin: "https://timeline-generator.ats030.workers.dev", "Content-Type": "application/json"}
});
assert.equal((await privateApi(oversized, env)).status, 413);
assert.equal(forwarded.length, 0);
const response = await privateApi(request(valid, "POST", "/api/private/jobs", {
  Origin: "https://timeline-generator.ats030.workers.dev", "Content-Type": "application/json", Cookie: "never-forward-cookie"
}), env);
assert.equal(response.status, 201);
assert.equal(response.headers.get("Cache-Control"), "no-store");
assert.equal(response.headers.get("Content-Security-Policy").includes("frame-ancestors 'none'"), true);
assert.equal((await response.json()).result.trace, undefined);
assert.equal(forwarded.length, 1);
assert.equal(forwarded[0].url, "http://127.0.0.1:8535/api/jobs");
assert.deepEqual(Object.keys(forwarded[0].options.headers).sort(), ["Authorization", "Content-Type"]);
env.PRIVATE_API.fetch = async () => new Response(null, {status: 302, headers: {Location: "https://evil.example"}});
assert.equal((await privateApi(request(), env)).status, 502);
env.PRIVATE_API.fetch = async () => { throw new Error("private upstream details"); };
const failure = await privateApi(request(), env);
assert.equal(failure.status, 502);
assert.equal((await failure.text()).includes("private upstream details"), false);
let assets = [];
env.ASSETS = {fetch: async request => {
  assets.push(new URL(request.url).pathname);
  assert.equal(request.headers.has("Cf-Access-Jwt-Assertion"), false);
  return new Response("shared HTML", {headers: {"Content-Type": "text/html", "Cache-Control": "public"}});
}};
assert.equal((await app.fetch(new Request("https://timeline-generator.ats030.workers.dev/manage"), {})).status, 503);
assert.equal((await app.fetch(new Request("https://timeline-generator.ats030.workers.dev/manage"), env)).status, 403);
const managed = await app.fetch(request(valid, "GET", "/manage"), env);
assert.equal(managed.status, 200);
assert.equal(managed.headers.get("Cache-Control"), "no-store");
assert.equal(await managed.text(), "shared HTML");
assert.equal((await app.fetch(request(valid, "GET", "/manage/timelines/1"), env)).status, 200);
assert.deepEqual(assets, ["/", "/detail"]);
assert.equal((await app.fetch(request(valid, "GET", "/manage/data/private.sqlite3"), env)).status, 404);
console.log("PASS: real RSA JWT validation, owner/issuer/audience/time checks, forged/unsigned denial, fixed JWKS, bounded reads, CSRF, private routes, token isolation, fixed VPC target, redirects and failures");
