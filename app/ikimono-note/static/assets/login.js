/* ログイン画面。失敗の理由はURLに載せず、印だけを見て文言はこちらで出す */
(function () {
  const params = new URLSearchParams(location.search);
  const message = document.getElementById("login-message");
  if (params.get("failed")) {
    message.hidden = false;
    message.className = "message error";
    message.textContent = "ログインできませんでした。もう一度お試しください。";
  }
  fetch("/api/me").then(r => {
    if (!r.ok) throw new Error("login state unavailable");
    return r.json();
  }).then(async state => {
    if (state.signed_in) {
      document.getElementById("google-login").hidden = true;
      message.hidden = false;
      message.className = "message";
      message.textContent = "設定を確認しています…";
      try {
        const response = await fetch("/api/settings");
        if (!response.ok) throw new Error("settings unavailable");
        const settings = await response.json();
        let stored = {}, hasStored = false;
        try {
          const raw = localStorage.getItem("species-public-settings");
          hasStored = !!raw;
          stored = JSON.parse(raw || "{}");
        } catch (_) { hasStored = true; }
        const provider = stored?.provider || settings.provider;
        const ready = provider === "local" || !!readApiKey(provider) || !!settings.trial;
        const hasKeys = ["gemini", "openai", "anthropic", "plantnet"].some(name => !!readApiKey(name));
        const next = ready ? "/" : !hasStored && !hasKeys && settings.provider === "gemini"
          ? "/settings?setup=gemini" : "/settings";
        location.replace(next);
      } catch (_) {
        message.className = "message error";
        message.textContent = "設定を確認できませんでした。設定画面を開いて、使うAIを確認してください。";
        document.getElementById("login-settings-fallback").hidden = false;
      }
      return;
    }
    if (!state.available) {
      document.getElementById("google-login").hidden = true;
      message.hidden = false;
      message.className = "message";
      message.textContent = "この生きものノートではログインがまだ設定されていません。運営者による設定が必要です。";
    }
  }).catch(() => {
    message.hidden = false;
    message.className = "message error";
    message.textContent = "ログイン状態を確認できませんでした。Googleログインをお試しください。";
  });
})();
