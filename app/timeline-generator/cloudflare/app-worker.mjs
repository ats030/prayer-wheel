// Shared UI with a read-only adapter for already published content.
// Private generation stays unavailable until an authenticated backend is verified.
import {configured, privateApi, verifyOwner} from "./private-api.mjs";
const notice = "公開年表は閲覧専用です。このブラウザへの保存と書き出しを利用できます。";
const csp = "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
function json(body, status = 200) {
  return Response.json(body, {status, headers: {
    "Cache-Control": "no-store", "Content-Security-Policy": csp,
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin"
  }});
}
async function published(request, env) {
  const url = new URL(request.url);
  url.pathname = "/published/showa.json";
  url.search = "";
  const response = await env.ASSETS.fetch(new Request(url));
  if (!response.ok) throw new Error("Publication unavailable");
  return response.json();
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path.startsWith("/api/private/")) return privateApi(request, env);
    if (path === "/manage" || path.startsWith("/manage/")) {
      if (!configured(env)) return json({error: "本人用の生成接続は準備中です。"}, 503);
      if (!await verifyOwner(request, env)) return json({error: "本人認証が必要です。"}, 403);
      if (!["GET", "HEAD"].includes(request.method)) return json({error: "操作できません。"}, 405);
      const page = path === "/manage" ? "/" : path === "/manage/quality" ? "/quality" :
        /^\/manage\/timelines\/[1-9]\d{0,17}$/.test(path) ? "/detail" : null;
      if (!page) return json({error: "画面が見つかりません。"}, 404);
      url.pathname = page;
      url.search = "";
      const asset = await env.ASSETS.fetch(new Request(url, {method: request.method}));
      const headers = new Headers(asset.headers);
      headers.set("Cache-Control", "no-store");
      return new Response(asset.body, {status: asset.status, headers});
    }
    if (path.startsWith("/api/")) {
      if (request.method !== "GET") return json({error: notice}, 503);
      if (path === "/api/capabilities") return json({generation_available: false, notice});
      if (!["/api/jobs", "/api/jobs/pub-showa", "/api/quality"].includes(path)) {
        return json({error: "年表が見つかりません。"}, 404);
      }
      if (path === "/api/quality") return json({jobs: [], notice: "公開資料には現在の評価結果がありません。"});
      try {
        const job = await published(request, env);
        if (path === "/api/jobs/pub-showa") return json(job);
        const raw = url.searchParams.get("offset") || "0";
        if (!/^\d{1,18}$/.test(raw) || !Number.isSafeInteger(Number(raw))) {
          return json({error: "一覧の開始位置が不正です。"}, 400);
        }
        const {result, ...summary} = job;
        return json({jobs: Number(raw) === 0 ? [summary] : [], total: 1,
          generation_available: false, notice, owner_login: configured(env) ? "/manage" : null});
      } catch {
        return json({error: "公開年表を読み込めませんでした。"}, 503);
      }
    }
    if (path === "/showa" || path === "/showa/") {
      url.pathname = "/timelines/pub-showa";
      return Response.redirect(url, 302);
    }
    if (path.startsWith("/timelines/")) {
      if (path === "/timelines/pub-showa/") {
        url.pathname = "/timelines/pub-showa";
        return Response.redirect(url, 302);
      }
      if (path !== "/timelines/pub-showa" || !["GET", "HEAD"].includes(request.method)) {
        return json({error: "年表が見つかりません。"}, 404);
      }
      url.pathname = "/detail.html";
      url.search = "";
      const response = await env.ASSETS.fetch(new Request(url, {method: request.method}));
      // The asset binding may redirect HTML extension URLs; follow only this fixed local mapping.
      if (response.status >= 300 && response.status < 400) {
        url.pathname = "/detail";
        return env.ASSETS.fetch(new Request(url, {method: request.method}));
      }
      return response;
    }
    return env.ASSETS.fetch(request);
  }
};
