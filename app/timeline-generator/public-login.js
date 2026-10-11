"use strict";
(() => {
  const status = document.querySelector("#login-status"), error = document.querySelector("#login-error");
  const start = document.querySelector("#login-start"), logout = document.querySelector("#login-logout"), retry = document.querySelector("#login-retry");
  let csrf = "", checking = false;
  const messages = {cancelled: "Googleでの本人確認を取り消しました。もう一度始められます。",
    unavailable: "Googleとの通信を完了できませんでした。しばらく待ってから、もう一度始めてください。",
    failed: "ログインを確認できませんでした。時間切れや別のタブでの操作が考えられます。もう一度始めてください。"};
  function showError(message) { error.textContent = message; error.hidden = !message; }
  function showSession(authenticated) {
    start.hidden = authenticated; logout.hidden = !authenticated; retry.hidden = true;
    start.disabled = false; logout.disabled = false;
    status.textContent = authenticated ? "ログインしています。" : "まだログインしていません。";
  }
  async function request(path, options = {}) {
    const response = await fetch(path, {...options, credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(15000)});
    const body = await response.json();
    return {response, body};
  }
  async function check() {
    if (checking) return;
    checking = true; retry.disabled = true; start.hidden = true; logout.hidden = true; csrf = "";
    status.textContent = "ログイン状態を確認しています。";
    try {
      const {response, body} = await request("/api/session");
      if (response.status === 401) { showSession(false); return; }
      if (!response.ok || body.authenticated !== true || typeof body.csrf_token !== "string") throw new Error();
      csrf = body.csrf_token; showSession(true);
    } catch {
      status.textContent = "ログイン状態を確認できません。";
      showError("通信を確認して、もう一度お試しください。"); retry.hidden = false;
    } finally { checking = false; retry.disabled = false; }
  }
  start.addEventListener("click", async () => {
    start.disabled = true; showError(""); status.textContent = "Googleのログイン画面へ移動します。";
    try {
      const {response, body} = await request("/auth/google/start", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
      if (!response.ok) throw new Error();
      const url = new URL(body.url);
      if (url.origin !== "https://accounts.google.com" || url.pathname !== "/o/oauth2/v2/auth") throw new Error();
      window.location.assign(url.href);
    } catch {
      start.disabled = false; status.textContent = "ログインを始められませんでした。";
      showError("受付が混み合っているか、通信を完了できませんでした。しばらく待ってから、もう一度お試しください。");
    }
  });
  logout.addEventListener("click", async () => {
    logout.disabled = true; showError("");
    try {
      const {response, body} = await request("/auth/logout", {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: "{}"});
      if (response.status === 401) { csrf = ""; showSession(false); status.textContent = "セッションの期限が切れました。"; return; }
      if (!response.ok || body.authenticated !== false) throw new Error();
      csrf = ""; showSession(false); status.textContent = "ログアウトしました。";
    } catch { logout.disabled = false; showError("ログアウトを確認できませんでした。もう一度お試しください。"); }
  });
  retry.addEventListener("click", () => { showError(""); check(); });
  const errorCode = new URLSearchParams(window.location.search).get("error");
  if (messages[errorCode]) showError(messages[errorCode]);
  // Remove transient callback outcome from the address/history; no tokens are stored.
  if (window.location.search) history.replaceState(null, "", window.location.pathname);
  check();
})();
