"use strict";
const $ = (id) => document.getElementById(id);
const stages = ["search", "read", "generate", "verify"];
let busy = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function fail(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = false;
  $("query").setAttribute("aria-invalid", "true");
}

function progress(data) {
  $("progress-message").textContent = data.message;
  const current = stages.indexOf(data.stage);
  document.querySelectorAll(".steps li").forEach((step, i) => {
    step.classList.toggle("current", i === current);
    step.classList.toggle("done", i < current);
    if (i === current) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
}

function render(data) {
  $("result-heading").textContent = data.theme;
  $("result-meta").textContent = `${data.period} · ${data.events.length}件 · ${data.elapsed_seconds}秒`;
  $("result-notice").textContent = data.notice;
  $("result-empty").hidden = data.events.length > 0;
  $("timeline").replaceChildren();
  for (const event of data.events) {
    const row = node("li", "event");
    row.append(node("div", "event-date", event.date));
    const body = node("div", "event-body");
    body.append(node("h3", "", event.title), node("p", "", event.description));
    const source = node("div", "source-row");
    const url = new URL(event.source.url);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("出典URLを読み取れませんでした。");
    const link = node("a", "source-link", "出典を読む ↗");
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `出典を読む：${event.source.title}（別タブ）`);
    source.append(link, node("span", "source-domain", url.hostname));
    const evidence = node("details");
    evidence.append(node("summary", "", "根拠を見る"), node("p", "quote-title", event.source.title), node("blockquote", "", event.quote));
    body.append(source, evidence);
    row.append(body);
    $("timeline").append(row);
  }
  $("result").hidden = false;
  $("result").focus({ preventScroll: true });
  $("result").scrollIntoView({ block: "start", behavior: "auto" });
}

async function search(event) {
  event.preventDefault();
  if (busy) return;
  const query = $("query").value.trim();
  $("form-error").hidden = true;
  $("query").removeAttribute("aria-invalid");
  if (!query) {
    fail("調べたいテーマを入力してください。");
    $("query").focus();
    return;
  }
  busy = true;
  $("submit").disabled = true;
  $("query").disabled = true;
  document.querySelectorAll("[data-query]").forEach((button) => { button.disabled = true; });
  $("submit").textContent = "作成中…";
  $("result").hidden = true;
  $("progress").hidden = false;
  $("search-form").setAttribute("aria-busy", "true");
  progress({ stage: "search", message: "検索を始めています。" });
  const start = Date.now();
  $("elapsed").textContent = "0秒";
  const timer = setInterval(() => { $("elapsed").textContent = `${Math.floor((Date.now() - start) / 1000)}秒`; }, 1000);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 195000);
  let received = false;
  try {
    const response = await fetch("/api/timeline", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query }), signal: controller.signal });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "検索を開始できませんでした。");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handle = (line) => {
      if (!line.trim()) return;
      const data = JSON.parse(line);
      if (data.kind === "progress") progress(data);
      if (data.kind === "error") throw new Error(data.message);
      if (data.kind === "result") { render(data); received = true; }
    };
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      lines.forEach(handle);
      if (done) { handle(buffer); break; }
    }
    if (!received) throw new Error("接続が途中で切れました。再検索してください。");
  } catch (error) {
    fail(error.name === "AbortError" ? "処理に時間がかかっています。少し待って、テーマを絞って再検索してください。" : error instanceof TypeError ? "接続できませんでした。ネットワークを確認して再検索してください。" : error.message);
    controller.abort();
  } finally {
    clearInterval(timer);
    clearTimeout(timeout);
    busy = false;
    $("submit").disabled = false;
    $("query").disabled = false;
    document.querySelectorAll("[data-query]").forEach((button) => { button.disabled = false; });
    $("submit").textContent = "年表を作る →";
    $("progress").hidden = true;
    $("search-form").removeAttribute("aria-busy");
    if (!received) $("query").focus();
  }
}

$("search-form").addEventListener("submit", search);
$("query").addEventListener("input", () => { $("query").removeAttribute("aria-invalid"); $("form-error").hidden = true; });
document.querySelectorAll("[data-query]").forEach((button) => button.addEventListener("click", () => {
  $("query").value = button.dataset.query;
  $("search-form").requestSubmit();
}));
$("refine").addEventListener("click", () => { $("query").focus(); $("query").scrollIntoView({ block: "center" }); });
