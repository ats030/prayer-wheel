/* 画面の明るさ切り替え。head 内で同期実行し、描画前に data-theme を確定させる。 */
(function () {
  var KEY = "species-theme";
  var ORDER = ["system", "light", "dark"];
  var LABEL = { system: "自動", light: "ライト", dark: "ダーク" };
  var ICON = { system: "◐", light: "☀", dark: "☽" };
  var BAR = { light: "#f4faf2", dark: "#121a14" };

  function stored() {
    try {
      var value = localStorage.getItem(KEY);
      return ORDER.indexOf(value) > 0 ? value : "system";
    } catch (error) {
      return "system";
    }
  }

  function paint(mode) {
    var root = document.documentElement;
    if (mode === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    var meta = document.getElementById("themeColorOverride");
    if (mode === "system") {
      if (meta) meta.remove();
      return;
    }
    if (!meta) {
      meta = document.createElement("meta");
      meta.id = "themeColorOverride";
      meta.name = "theme-color";
      document.head.prepend(meta);
    }
    meta.content = BAR[mode];
  }

  paint(stored());

  function label(button, mode) {
    /* 狭い画面ではラベルだけをCSSで畳むため、アイコンと文字を別の要素に分ける */
    button.textContent = "";
    var icon = document.createElement("span");
    icon.className = "theme-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = ICON[mode];
    var text = document.createElement("span");
    text.className = "theme-label";
    text.textContent = LABEL[mode];
    button.append(icon, text);
    button.setAttribute("aria-label", "画面の明るさ：" + LABEL[mode] + "。押すと切り替わります");
    button.title = "画面の明るさ：" + LABEL[mode] + "（自動は端末の設定に合わせます）";
  }

  function connect() {
    var button = document.getElementById("themeToggle");
    if (!button) return;
    var mode = stored();
    label(button, mode);
    button.addEventListener("click", function () {
      mode = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
      try {
        if (mode === "system") localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, mode);
      } catch (error) {
        /* プライベートモードなどで保存できない場合も、その場の切り替えは効かせる */
      }
      paint(mode);
      label(button, mode);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connect);
  else connect();
})();
