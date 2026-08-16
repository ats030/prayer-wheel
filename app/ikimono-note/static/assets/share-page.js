/* 公開ページを出した本人にだけ出る取り消しボタン。記録を消したあとや別の端末からでも、
   このページを開けば公開を止められる。CSP が 'unsafe-inline' を許さないので、
   ボタンの結び付けはここで行う */
(function () {
  var button = document.getElementById("revokeShare");
  if (!button) return;
  var message = document.getElementById("revokeMessage");
  button.addEventListener("click", async function () {
    button.disabled = true;
    message.textContent = "取り消しています…";
    try {
      var response = await fetch("/api/share/" + encodeURIComponent(button.dataset.token) + "/delete",
                                 {method: "POST"});
      if (!response.ok) {
        var data = await response.json().catch(function () { return {}; });
        throw new Error(data.detail || "取り消せませんでした。");
      }
      message.textContent = "公開を取り消しました。このページはもう開けません。";
      button.remove();
      var photo = document.querySelector(".share-photo");
      if (photo) photo.remove();
    } catch (error) {
      button.disabled = false;
      message.textContent = error.message;
    }
  });
})();
