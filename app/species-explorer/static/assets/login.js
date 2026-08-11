/* ログイン画面。失敗の理由はURLに載せず、印だけを見て文言はこちらで出す */
(function () {
  const params = new URLSearchParams(location.search);
  const message = document.getElementById("login-message");
  if (params.get("failed")) {
    message.hidden = false;
    message.className = "message error";
    message.textContent = "ログインできませんでした。もう一度お試しください。";
  }
  fetch("/api/me").then(r => r.json()).then(state => {
    if (state.signed_in) { location.replace("/"); return; }
    if (!state.available) {
      document.getElementById("google-login").hidden = true;
      message.hidden = false;
      message.className = "message";
      message.textContent = "この生きものノートではログインがまだ設定されていません。運営者による設定が必要です。";
    }
  }).catch(() => { /* 出せなくてもログイン自体は試せる */ });
})();
