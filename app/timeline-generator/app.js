"use strict";
const $ = (id) => document.getElementById(id);
const stages = ["search", "read", "generate", "verify"];
const labels = {queued: "待機中", running: "生成中", complete: "完了", failed: "失敗"};
const active = job => ["queued", "running"].includes(job.state);
function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function date(value) { return new Date(value).toLocaleString("ja-JP"); }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "処理を完了できませんでした。");
  return data;
}
function error(id, message) { $(id).textContent = message; $(id).hidden = false; }
function progress(data) {
  $("progress-message").textContent = data.message || "生成を始めています。";
  const current = stages.indexOf(data.stage);
  document.querySelectorAll(".steps li").forEach((step, i) => {
    step.classList.toggle("current", i === current);
    step.classList.toggle("done", i < current);
    if (i === current) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
}
function sourceLink(source, text, optional = false) {
  let url;
  try { url = new URL(source.url); }
  catch { if (optional) return null; throw new Error("出典URLを読み取れませんでした。"); }
  if (!["http:", "https:"].includes(url.protocol)) {
    if (optional) return null;
    throw new Error("出典URLを読み取れませんでした。");
  }
  const link = node("a", "source-link", text);
  link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.title = source.title;
  link.setAttribute("aria-label", `出典を読む：${source.title}（別タブ）`);
  return link;
}
function render(data) {
  $("result-meta").textContent = `${data.events.length}件`;
  $("generation-meta").textContent = `${data.period} · 生成時間 ${data.elapsed_seconds}秒`;
  $("generation-notice").textContent = data.notice;
  const alerts = [];
  if (data.stop_reason === "time_limit") alerts.push(`時間上限（10分）により終了。検証済み${data.events.length}件を保存しました。`);
  if (data.stop_reason === "processing_error") alerts.push(`途中で処理を終了。検証済み${data.events.length}件を保存しました。再生成で調べ直せます。`);
  if (data.review_notes?.length) alerts.push(`採用を見送った候補${data.review_notes.length}件。詳細は「生成情報」で確認できます。`);
  $("result-notice").textContent = alerts.join(" ");
  $("result-notice").hidden = alerts.length === 0;
  $("review-notes").replaceChildren();
  for (const note of data.review_notes || []) {
    const item = node("div", "review-note");
    item.append(node("p", "", `${note.date} ${note.title}：${note.reason}`));
    for (const source of note.sources || []) {
      const link = sourceLink(source, `補足資料：${source.title} ↗`, true);
      if (link) item.append(link);
    }
    $("review-notes").append(item);
  }
  $("result-empty").hidden = data.events.length > 0;
  $("timeline").replaceChildren();
  const rows = document.createDocumentFragment();
  for (const event of data.events) {
    const row = node("li", "event");
    row.append(node("div", "event-date", event.date), node("h3", "event-title", event.title), node("p", "event-description", event.description), sourceLink(event.source, "出典 ↗"));
    rows.append(row);
  }
  $("timeline").append(rows);
  $("result").hidden = false;
}


if ($("search-form")) {
  let submitting = false;
  $("search-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    const query = $("query").value.trim();
    $("form-error").hidden = true;
    $("query").removeAttribute("aria-invalid");
    if (!query) {
      error("form-error", "調べたいテーマを入力してください。");
      $("query").setAttribute("aria-invalid", "true");
      $("query").focus();
      return;
    }
    submitting = true;
    $("submit").disabled = true;
    $("search-form").setAttribute("aria-busy", "true");
    try {
      const job = await api("/api/jobs", {query});
      if (job.has_result) { location.assign(`/timelines/${job.id}`); return; }
      $("receipt").hidden = false;
      $("receipt-heading").textContent = job.state === "failed" ? "前回の生成は失敗しました" : "キューに登録されています";
      $("receipt-message").textContent = `${job.query} · ${labels[job.state]}。別のテーマも追加できます。`;
      $("receipt-link").href = `/timelines/${job.id}`;
    } catch (exc) { error("form-error", exc.message || "接続できませんでした。もう一度お試しください。"); }
    finally {
      submitting = false;
      $("submit").disabled = false;
      $("search-form").removeAttribute("aria-busy");
    }
  });
  $("query").addEventListener("input", () => { $("query").removeAttribute("aria-invalid"); $("form-error").hidden = true; });
  document.querySelectorAll("[data-query]").forEach(button => button.addEventListener("click", () => {
    $("query").value = button.dataset.query;
    $("search-form").requestSubmit();
  }));
  const query = new URLSearchParams(location.search).get("query");
  if (query) $("query").value = query;
}

if ($("job-list")) {
  let offset = 0, timer, loading = false;
  async function load() {
    clearTimeout(timer);
    if (loading) return;
    loading = true;
    try {
      const data = await api(`/api/jobs?offset=${offset}`);
      $("page-error").hidden = true;
      $("list-summary").textContent = data.total ? `${data.total}件中 ${offset + 1}〜${offset + data.jobs.length}件` : "0件";
      $("list-empty").hidden = data.total > 0;
      const list = document.createDocumentFragment();
      for (const job of data.jobs) {
        const row = node("li", "job-row");
        const link = node("a", "job-link", job.query);
        link.href = `/timelines/${job.id}`;
        const state = node("span", "job-state", labels[job.state]);
        state.dataset.state = job.state;
        const count = node("span", "job-count", Number.isInteger(job.event_count) ? `${job.event_count}件` : "—");
        const previous = job.has_result && job.state !== "complete";
        count.setAttribute("aria-label", Number.isInteger(job.event_count) ? `${previous ? "前回の" : ""}収録件数 ${job.event_count}件` : "未生成");
        if (previous) count.append(node("small", "", "前回"));
        row.append(link, state, count);
        const message = job.error || (active(job) || ["time_limit", "processing_error"].includes(job.stop_reason) ? job.message : "");
        if (message) row.append(node("p", "help", message));
        list.append(row);
      }
      // Unchanged polling responses leave focused links and screen reader position intact.
      const signature = JSON.stringify(data.jobs);
      if ($("job-list").dataset.signature !== signature) {
        const focused = document.activeElement;
        const href = $("job-list").contains(focused) ? focused.getAttribute("href") : null;
        $("job-list").replaceChildren(list);
        $("job-list").dataset.signature = signature;
        if (href) [...$("job-list").querySelectorAll("a")].find(link => link.getAttribute("href") === href)?.focus({preventScroll: true});
      }
      $("previous").disabled = offset === 0;
      $("next").disabled = offset + data.jobs.length >= data.total;
    } catch (exc) { error("page-error", `一覧を読み込めませんでした。${exc.message}`); }
    finally { loading = false; timer = setTimeout(load, 3000); }
  }
  $("previous").addEventListener("click", () => { if (!loading) { offset = Math.max(0, offset - 50); load(); } });
  $("next").addEventListener("click", () => { if (!loading) { offset += 50; load(); } });
  load();
}

if ($("job-status")) {
  const id = location.pathname.split("/").pop();
  let timer, generatedAt, renderedResult, job, acting = false, generation = 0;
  function show(current) {
    job = current;
    $("page-heading").textContent = job.query;
    document.title = `${job.query} · 歴史年表`;
    $("job-status").textContent = labels[job.state];
    $("job-status").dataset.state = job.state;
    $("result-meta").hidden = !job.result;
    $("generation-info").hidden = !job.result;
    $("job-message").textContent = job.message || "";
    $("job-message").hidden = job.state !== "queued";
    $("retry").hidden = job.state !== "failed";
    $("regenerate").hidden = !job.has_result || active(job);
    $("refine").href = `/?query=${encodeURIComponent(job.query)}`;
    $("progress").hidden = job.state !== "running";
    if (job.state === "running") progress(job);
    if (job.error) error("page-error", job.error);
    else $("page-error").hidden = true;
    if (job.result && (generatedAt !== job.generated_at || renderedResult !== JSON.stringify(job.result))) {
      render(job.result);
      generatedAt = job.generated_at;
      renderedResult = JSON.stringify(job.result);
      $("saved-at").textContent = `生成日時：${date(job.generated_at)}`;
    }
    $("old-result").hidden = !job.has_result || job.state === "complete";
  }
  async function load() {
    clearTimeout(timer);
    const version = generation;
    try {
      const current = await api(`/api/jobs/${id}`);
      if (version === generation && !acting) show(current);
    } catch (exc) {
      if (version === generation && !acting) error("page-error", `状態を読み込めませんでした。${exc.message}`);
    }
    if (version === generation && !acting) timer = setTimeout(load, 2000);
  }
  for (const action of ["retry", "regenerate"]) $(action).addEventListener("click", async () => {
    if (acting) return;
    acting = true;
    generation += 1;
    clearTimeout(timer);
    $("retry").disabled = $("regenerate").disabled = true;
    try { show(await api(`/api/jobs/${id}/${action}`, {})); }
    catch (exc) { error("page-error", exc.message); }
    finally { acting = false; $("retry").disabled = $("regenerate").disabled = false; timer = setTimeout(load, 2000); }
  });
  load();
}
