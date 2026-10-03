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
function shortDate(value) { return new Date(value).toLocaleString("ja-JP", {year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}); }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000)});
  const data = await response.json();
  if (!response.ok) {
    const failure = new Error(data.error || "処理を完了できませんでした。");
    failure.status = response.status;
    throw failure;
  }
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
function sourceSummary(events) {
  const counts = new Map();
  for (const event of events) {
    let host;
    try { host = new URL(event.source?.url).hostname.replace(/^www\./, ""); } catch { continue; }
    counts.set(host, (counts.get(host) || 0) + 1);
  }
  if (!counts.size) return "";
  const sorted = [...counts].sort((a, b) => b[1] - a[1]);
  const shown = sorted.slice(0, 3).map(([host, count]) => `${host} ${count}件`).join("、");
  return `出典 ${counts.size}サイト：${shown}${sorted.length > 3 ? `、ほか${sorted.length - 3}サイト` : ""}`;
}
function renderQuality(quality) {
  const box = $("quality");
  box.replaceChildren();
  if (!quality) return;
  const gold = node("div", "quality-block");
  gold.append(node("h3", "quality-heading", `正解集合との照合（人手で選んだ主要項目・検証日 ${quality.gold_verified_at}）`));
  if (quality.theme === null) {
    gold.append(node("p", "", "このテーマは正解集合の対象外のため、網羅性は評価していません。"));
  } else {
    const total = quality.found.length + quality.missing.length;
    gold.append(node("p", "", total ? `主要項目 ${quality.found.length} / ${total}件を収録（${Math.round(quality.recall * 100)}%）` : "指定期間に該当する主要項目はありません。"));
    if (quality.missing.length) gold.append(node("p", "", `欠落：${quality.missing.map(item => item.label).join("、")}`));
    for (const item of quality.known_errors) gold.append(node("p", "quality-error", `既知の誤りに一致：${item.label} ← ${item.year} ${item.event}`));
  }
  const src = quality.sources || {};
  const kinds = Object.entries(src.kinds || {}).map(([kind, count]) => `${kind} ${count}件`).join("、");
  const sources = node("div", "quality-block");
  sources.append(node("h3", "quality-heading", "出典の機械的な集計（内容の正しさの判定ではありません）"));
  if (kinds) sources.append(node("p", "", `種別：${kinds}`));
  if (src.top_domain) sources.append(node("p", "", `最多の出典：${src.top_domain}（${Math.round(src.top_domain_share * 100)}%）`));
  sources.append(node("p", "", `重複の疑い：${quality.duplicates.length}組`));
  box.append(gold, sources);
}
function render(data, job) {
  renderQuality(job.quality);
  $("result-meta").textContent = `${data.events.length}件`;
  $("generation-meta").textContent = `${job.period || "全期間"} · 生成時間 ${data.elapsed_seconds}秒`;
  $("source-summary").textContent = sourceSummary(data.events);
  $("generation-notice").textContent = data.notice;
  const alerts = [];
  if (data.stop_reason === "time_limit") alerts.push(`時間上限により終了。検証済み${data.events.length}件を保存しました。`);
  if (data.stop_reason === "processing_error") alerts.push(`途中で処理を終了。検証済み${data.events.length}件を保存しました。${job.legacy_period ? "年代条件を外して新しく登録できます。" : "再生成で調べ直せます。"}`);
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
      document.dispatchEvent(new Event("job-registered"));
    } catch (exc) {
      error("form-error", exc.message || "接続できませんでした。もう一度お試しください。");
      if (exc.status === 400) {
        $("query").setAttribute("aria-invalid", "true");
        $("query").focus();
      }
    }
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
  let offset = 0, timer, loading = false, refreshPending = false, deleting = false;
  async function load() {
    clearTimeout(timer);
    if (loading) return;
    if (deleting) { timer = setTimeout(load, 3000); return; }
    loading = true;
    try {
      const data = await api(`/api/jobs?offset=${offset}`);
      if (deleting) return;
      if (offset > 0 && !data.jobs.length) { refreshPending = true; return; }
      $("page-error").hidden = true;
      $("list-summary").textContent = data.total ? `${data.total}件中 ${offset + 1}〜${offset + data.jobs.length}件` : "0件";
      $("list-empty").hidden = data.total > 0;
      const list = document.createDocumentFragment();
      for (const job of data.jobs) {
        const row = node("li", "job-row");
        const link = node("a", "job-link", job.query);
        link.href = `/timelines/${job.id}`;
        const theme = node("div", "job-theme");
        const updated = node("time", "job-updated", `更新 ${shortDate(job.updated_at)}`);
        updated.dateTime = job.updated_at;
        theme.append(link, updated);
        const state = node("span", "job-state", labels[job.state]);
        state.dataset.state = job.state;
        const count = node("span", "job-count", Number.isInteger(job.event_count) ? `${job.event_count}件` : "—");
        const previous = job.has_result && job.state !== "complete";
        count.setAttribute("aria-label", Number.isInteger(job.event_count) ? `${previous ? "前回の" : ""}収録件数 ${job.event_count}件` : "未生成");
        if (previous) count.append(node("small", "", "前回"));
        const remove = node("button", "text-button job-delete", "削除");
        remove.type = "button";
        remove.dataset.id = job.id;
        remove.disabled = !job.can_delete;
        remove.setAttribute("aria-label", `${job.query}を削除`);
        remove.title = job.can_delete ? "登録と保存結果を削除" : "収録済みのため削除できません";
        remove.addEventListener("click", async () => {
          if (deleting || !confirm(`「${job.query}」を削除しますか？登録と保存結果は元に戻せません。${active(job) ? "待機・生成中の処理も取り消します。" : ""}`)) return;
          deleting = true;
          let removed = false;
          clearTimeout(timer);
          remove.disabled = true;
          $("delete-error").hidden = true;
          $("delete-status").hidden = true;
          try {
            await api(`/api/jobs/${job.id}/delete`, {});
            removed = true;
            $("delete-status").textContent = `「${job.query}」を削除しました。`;
            $("delete-status").hidden = false;
            $("delete-status").focus({preventScroll: true});
          } catch (exc) { error("delete-error", exc.message || "削除できませんでした。"); }
          finally {
            deleting = false;
            remove.disabled = removed || !job.can_delete;
            if (loading) refreshPending = true;
            else { offset = 0; load(); }
          }
        });
        row.append(theme, state, count, remove);
        const message = job.error || (active(job) || ["time_limit", "processing_error"].includes(job.stop_reason) ? job.message : "");
        const notes = [!job.can_delete ? "収録済みのため削除できません" : "", job.legacy_period ? "期間限定・閲覧専用" : "", message].filter(Boolean);
        if (notes.length) row.append(node("p", "help", notes.join("。")));
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
    finally {
      loading = false;
      if (refreshPending) { refreshPending = false; offset = 0; load(); }
      else timer = setTimeout(load, 3000);
    }
  }
  document.addEventListener("job-registered", () => {
    if (loading) { refreshPending = true; return; }
    offset = 0;
    load();
  });
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
    $("retry").hidden = job.legacy_period || job.state !== "failed";
    $("regenerate").hidden = job.legacy_period || !job.has_result || active(job);
    $("refine").textContent = job.legacy_period ? "全期間で新規登録" : "条件を変える";
    $("refine").href = `/?query=${encodeURIComponent(job.legacy_period ? job.topic : job.query)}`;
    $("legacy-period").hidden = !job.legacy_period;
    $("legacy-period").textContent = job.legacy_period ? `期間限定（${job.period}）の保存済み年表です。閲覧専用のため、年代条件を外して新しく登録してください。` : "";
    $("progress").hidden = job.state !== "running";
    if (job.state === "running") progress(job);
    if (job.error) error("page-error", job.error);
    else $("page-error").hidden = true;
    if (job.result && (generatedAt !== job.generated_at || renderedResult !== JSON.stringify(job.result))) {
      render(job.result, job);
      generatedAt = job.generated_at;
      renderedResult = JSON.stringify(job.result);
      $("saved-at").textContent = `生成日時：${date(job.generated_at)}`;
    }
    $("old-result").hidden = job.legacy_period || !job.has_result || job.state === "complete";
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
