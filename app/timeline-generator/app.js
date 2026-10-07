"use strict";
const $ = (id) => document.getElementById(id);
const stages = ["search", "read", "generate", "verify"];
const labels = {queued: "待機中", running: "生成中", complete: "完了", failed: "失敗", cancelled: "中止"};
const active = job => ["queued", "running"].includes(job.state);
const endings = {time_limit: "時間上限", processing_error: "途中終了"};
const stateLabel = job => labels[job.state] + (job.state === "complete" && endings[job.stop_reason] ? `（${endings[job.stop_reason]}）` : "");
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
const passLabels = {true: "目標内", false: "目標外"};
function axisRow(axis, title = axis.label, withNote = true) {
  const row = node("li", "axis");
  row.append(node("span", "axis-label", title));
  const track = node("span", "axis-track");
  track.setAttribute("aria-hidden", "true");
  if (axis.value !== null) {
    const fill = node("span", `axis-fill${axis.passed === false ? " is-off" : axis.passed === null ? " is-neutral" : ""}`);
    fill.style.width = `${Math.round(axis.value * 100)}%`;
    track.append(fill);
  }
  if (axis.target !== null) {
    const mark = node("span", "axis-target");
    mark.style.left = `${Math.round(axis.target * 100)}%`;
    track.append(mark);
  }
  if (axis.value !== null) row.append(track);
  const percent = axis.value === null ? "" : `${Math.round(axis.value * 100)}% · `;
  const target = axis.target === null ? "" : ` · 目標${Math.round(axis.target * 100)}%`;
  row.append(node("span", "axis-value", `${percent}${axis.display}${target}`));
  if (axis.passed !== null) row.append(node("span", `axis-chip${axis.passed ? "" : " is-off"}`, passLabels[axis.passed]));
  else if (axis.key === "recall" && axis.value === null) row.append(node("span", "axis-chip is-na", "対象外"));
  if (withNote && axis.note) row.append(node("span", "axis-note", axis.note));
  return row;
}
function renderQuality(quality) {
  const box = $("quality");
  box.replaceChildren();
  $("quality-section").hidden = !quality;
  $("quality-link").hidden = !quality;
  if (!quality) return;
  const off = quality.axes.filter((axis) => axis.passed === false).length;
  $("quality-link").textContent = off ? `評価 目標外${off}` : "評価 すべて目標内";
  $("quality-basis").textContent = `再現率と既知の誤りは人手で選んだ主要項目（検証日 ${quality.gold_verified_at}）との照合です。出典の割合は機械的な集計で、内容の正しさの判定ではありません。総合点は出していません。`;
  const list = node("ul", "axes");
  for (const axis of quality.axes) list.append(axisRow(axis));
  box.append(list);
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
      $("receipt-heading").textContent = job.state === "failed" ? "前回の生成は失敗しました" : job.state === "cancelled" ? "前回の処理は中止しました" : "キューに登録されています";
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
        const updated = node("time", "job-updated");
        updated.append(node("span", "job-updated-label", "更新 "), shortDate(job.updated_at));
        updated.dateTime = job.updated_at;
        const state = node("span", "job-state", stateLabel(job));
        state.dataset.state = job.state;
        // Narrow screens group state and time on one line; wide screens dissolve the group into table cells.
        const meta = node("span", "job-meta");
        meta.append(state, updated);
        const count = node("span", "job-count", Number.isInteger(job.event_count) ? `${job.event_count}件` : "—");
        const previous = job.has_result && job.state !== "complete";
        count.setAttribute("aria-label", Number.isInteger(job.event_count) ? `${previous ? "前回の" : ""}収録件数 ${job.event_count}件` : "未生成");
        if (previous) count.append(node("small", "", "前回"));
        const remove = node("button", "text-button job-delete", "削除");
        remove.type = "button";
        remove.dataset.id = job.id;
        remove.setAttribute("aria-label", `${job.query}を削除`);
        remove.title = "登録と保存結果を削除";
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
            remove.disabled = removed;
            if (loading) refreshPending = true;
            else { offset = 0; load(); }
          }
        });
        const cancel = node("button", "text-button job-cancel", "中止");
        cancel.type = "button";
        cancel.setAttribute("aria-label", `${job.query}の処理を中止`);
        cancel.title = "待機・生成中の処理を中止（登録は残します）";
        cancel.addEventListener("click", async () => {
          if (deleting || !confirm(`「${job.query}」の処理を中止しますか？検証途中の出来事は保存されません。${job.has_result ? "前回の結果は残ります。" : "再試行で生成し直せます。"}`)) return;
          deleting = true;
          clearTimeout(timer);
          cancel.disabled = true;
          $("delete-error").hidden = true;
          $("delete-status").hidden = true;
          try {
            await api(`/api/jobs/${job.id}/cancel`, {});
            $("delete-status").textContent = `「${job.query}」の処理を中止しました。`;
            $("delete-status").hidden = false;
            $("delete-status").focus({preventScroll: true});
          } catch (exc) { error("delete-error", exc.message || "中止できませんでした。"); }
          finally {
            deleting = false;
            cancel.disabled = false;
            if (loading) refreshPending = true;
            else load();
          }
        });
        // Saved timelines cannot be deleted; showing only usable buttons keeps rows short.
        const ops = [...(active(job) ? [cancel] : []), ...(job.can_delete ? [remove] : [])];
        const cell = node("span", "job-ops");
        cell.append(...ops);
        row.append(link, meta, count, ...(ops.length ? [cell] : []));
        // Failure details and the time-limit notice live on the detail page; the list keeps progress only.
        const notes = [job.legacy_period ? "期間限定・閲覧専用" : "", active(job) ? job.message : ""].filter(Boolean);
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
      $("pagination").hidden = offset === 0 && data.total <= 50;
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
  let editorRevision, editorDirty = false;
  const milestoneRows = $("milestones-rows");
  function addMilestone(item = {}) {
    if (milestoneRows.children.length >= 12) return;
    const row = node("div", "milestone-row");
    for (const [key, label, type, max] of [["name", "出来事の名前（必須）", "text", 120], ["year", "年代（任意）", "number"], ["note", "補足（任意）", "text", 300], ["url", "参考URL（任意）", "url", 1000]]) {
      const field = node("label", null, label);
      const input = node("input");
      input.type = type; input.dataset.key = key; input.value = item[key] ?? "";
      if (max) input.maxLength = max;
      if (key === "name") input.required = true;
      if (key === "year") { input.min = -9999; input.max = 9999; input.step = 1; }
      input.addEventListener("input", () => { editorDirty = true; $("milestones-message").textContent = "未保存の変更があります。"; });
      field.append(input); row.append(field);
    }
    const remove = node("button", "text-button", "この項目を外す");
    remove.type = "button";
    remove.addEventListener("click", () => { row.remove(); editorDirty = true; $("milestone-add").disabled = false; $("milestones-message").textContent = "未保存の変更があります。"; $("milestone-add").focus(); });
    row.append(remove); milestoneRows.append(row);
    $("milestone-add").disabled = milestoneRows.children.length >= 12;
    return row;
  }
  function fillMilestones(items) {
    milestoneRows.replaceChildren();
    $("milestone-add").disabled = false;
    for (const item of items) addMilestone(item);
  }
  function showMilestones(current) {
    $("milestones-section").hidden = current.legacy_period;
    $("milestones-fields").disabled = active(current) || acting;
    $("milestone-import").hidden = !(current.suggested_milestones || []).length;
    const revision = current.milestones_revision ?? 0;
    if (editorRevision !== revision) {
      if (!editorDirty) { fillMilestones(current.requested_milestones || []); editorRevision = revision; }
      else $("milestones-message").textContent = "別の画面で保存内容が変わりました。入力は保持しています。「保存内容に戻す」で読み直してください。";
    }
    const rows = (current.milestone_report || []).map(item => {
      const status = {found: "一致する項目あり", pending: "次回調査", missing: "未確認", mismatch: "指定年と相違"}[item.status];
      const li = node("li", null, `${item.name}${item.year == null ? "" : `（${item.year}年）`} — ${status}。${item.reason}`);
      return li;
    });
    if (!rows.length) rows.push(node("li", null, "主要項目はまだ指定されていません。"));
    $("milestone-report").replaceChildren(...rows);
  }
  $("milestone-add").addEventListener("click", () => { const row = addMilestone(); if (row) { editorDirty = true; $("milestones-message").textContent = "未保存の変更があります。"; row.querySelector("input").focus(); } });
  $("milestone-import").addEventListener("click", () => {
    const existing = [...milestoneRows.querySelectorAll('[data-key="name"]')].map(input => input.value);
    for (const item of job.suggested_milestones || []) if (!existing.includes(item.name)) addMilestone(item);
    editorDirty = true; $("milestones-message").textContent = "取り込んだ項目は未保存です。";
  });
  $("milestone-reload").addEventListener("click", () => { fillMilestones(job.requested_milestones || []); editorDirty = false; editorRevision = job.milestones_revision ?? 0; $("milestones-message").textContent = "保存内容に戻しました。"; $("milestones-error").hidden = true; });
  $("milestones-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (acting || active(job)) return;
    const items = [...milestoneRows.children].map(row => Object.fromEntries([...row.querySelectorAll("input")].map(input => [input.dataset.key, input.dataset.key === "year" ? (input.value === "" ? null : Number(input.value)) : input.value])));
    acting = true; generation += 1; clearTimeout(timer);
    $("milestones-fields").disabled = true;
    $("milestones-error").hidden = true;
    try {
      const saved = await api(`/api/jobs/${id}/milestones`, {items, revision: editorRevision});
      editorDirty = false; editorRevision = undefined;
      saved.suggested_milestones = job.suggested_milestones;
      show(saved);
      $("milestones-message").textContent = "主要項目を保存しました。再生成で反映します。";
    } catch (exc) { error("milestones-error", exc.message); }
    finally { acting = false; $("milestones-fields").disabled = active(job); timer = setTimeout(load, 2000); }
  });
  function show(current) {
    job = current;
    showMilestones(current);
    $("page-heading").textContent = job.query;
    document.title = `${job.query} · 歴史年表`;
    $("job-status").textContent = labels[job.state];
    $("job-status").dataset.state = job.state;
    $("result-meta").hidden = !job.result;
    $("generation-info").hidden = !job.result;
    $("job-message").textContent = job.message || "";
    $("job-message").hidden = job.state !== "queued" && !(job.message || "").startsWith("処理を中止しました");
    $("retry").hidden = job.legacy_period || !["failed", "cancelled"].includes(job.state);
    $("cancel").hidden = !active(job);
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
  for (const action of ["retry", "regenerate", "cancel"]) $(action).addEventListener("click", async () => {
    if (acting) return;
    if (["regenerate", "retry"].includes(action) && editorDirty) { error("milestones-error", `主要項目の変更を保存してから${action === "retry" ? "再試行" : "再生成"}してください。`); $("milestones-editor").open = true; return; }
    if (action === "cancel" && !confirm(`処理を中止しますか？検証途中の出来事は保存されません。${job.has_result ? "前回の結果は残ります。" : "再試行で生成し直せます。"}`)) return;
    acting = true;
    generation += 1;
    clearTimeout(timer);
    $("retry").disabled = $("regenerate").disabled = $("cancel").disabled = true;
    try { show(await api(`/api/jobs/${id}/${action}`, {})); }
    catch (exc) { error("page-error", exc.message); }
    finally { acting = false; $("retry").disabled = $("regenerate").disabled = $("cancel").disabled = false; $("milestones-fields").disabled = active(job); timer = setTimeout(load, 2000); }
  });
  load();
}

if ($("quality-axes")) {
  (async () => {
    try {
      const data = await api("/api/quality");
      $("quality-summary").textContent = data.jobs.length ? `結果のある年表 ${data.jobs.length}件を比較しています（新しい順）。` : "比較できる年表がまだありません。";
      const sections = document.createDocumentFragment();
      // 正解集合外のテーマは軸が少ないため、軸の多い行の順を基準に全件の軸を集める。
      const axisKeys = new Map();
      for (const job of [...data.jobs].sort((a, b) => b.axes.length - a.axes.length)) for (const axis of job.axes) if (!axisKeys.has(axis.key)) axisKeys.set(axis.key, axis);
      for (const first of axisKeys.values()) {
        const section = node("section", "quality-axis");
        section.append(node("h2", "quality-heading", first.label));
        const list = node("ul", "axes");
        for (const job of data.jobs) {
          const axis = job.axes.find(item => item.key === first.key);
          if (!axis) continue;
          const row = axisRow(axis, "", false);
          const link = node("a", "axis-label", job.query);
          link.href = `/timelines/${job.id}`;
          row.firstChild.replaceWith(link);
          list.append(row);
        }
        section.append(list);
        sections.append(section);
      }
      $("quality-axes").replaceChildren(sections);
    } catch (exc) { error("page-error", `評価を読み込めませんでした。${exc.message}`); }
  })();
}
