"use strict";
// Portable records deliberately exclude raw quotations, traces and credentials.
window.TimelineLibrary = (() => {
  const FORMAT = "timeline-generator-library", VERSION = 1, LIMIT = 100, MAX_BYTES = 8 * 1024 * 1024;
  function text(value, max, optional = false) {
    if (optional && value == null) return "";
    if (typeof value !== "string" || value.length > max || (!optional && !value.trim())) throw new Error("年表ファイルの文字項目を確認してください。");
    return value;
  }
  function normalize(record) {
    if (!record || !Array.isArray(record.events) || record.events.length > 50) throw new Error("出来事は年表ごとに50件までです。");
    return {
      theme: text(record.theme, 180), period: text(record.period, 180),
      generated_at: text(record.generated_at, 80, true), notice: text(record.notice, 4000, true),
      source_mode: ["wikipedia", "searxng"].includes(record.source_mode) ? record.source_mode : "unknown",
      events: record.events.map(event => {
        if (!event || !Number.isInteger(event.year) || Math.abs(event.year) > 1000000) throw new Error("出来事の年代を確認してください。");
        const source = event.source;
        const url = new URL(text(source?.url, 2000));
        if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) throw new Error("出典にはHTTP/HTTPSのURLを指定してください。");
        return {year: event.year, date: text(event.date, 120), title: text(event.title, 300), description: text(event.description, 4000, true), source: {title: text(source.title, 500), url: url.href}};
      })
    };
  }
  function fromJob(job) {
    if (!job.result) throw new Error("生成結果がありません。");
    return normalize({...job.result, theme: job.result.theme || job.query, period: job.period || "全期間", generated_at: job.generated_at});
  }
  function serialize(records) {
    const body = JSON.stringify({format: FORMAT, version: VERSION, timelines: records.map(normalize)}, null, 2);
    if (new TextEncoder().encode(body).length > MAX_BYTES) throw new Error("端末保存とバックアップは全体で8MiBまでです。書き出してから不要な年表を削除してください。");
    return body;
  }
  function open() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("timeline-generator-library", 1);
      request.onupgradeneeded = () => request.result.createObjectStore("timelines", {keyPath: "id", autoIncrement: true});
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error("端末に保存できません。ブラウザの保存設定を確認し、ファイルへ書き出してください。"));
      request.onblocked = () => reject(new Error("別のタブを閉じてから、もう一度お試しください。"));
    });
  }
  async function list() {
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction("timelines", "readonly");
        const request = transaction.objectStore("timelines").getAll();
        transaction.oncomplete = () => resolve(request.result);
        transaction.onerror = transaction.onabort = () => reject(new Error("端末の年表を読み込めませんでした。"));
      });
    } finally { db.close(); }
  }
  async function save(records) {
    const checked = records.map(normalize); // Validate every record before starting a write.
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction("timelines", "readwrite");
        const store = transaction.objectStore("timelines");
        let added = 0, failure;
        const request = store.getAll();
        request.onsuccess = () => {
          const existing = new Set(request.result.map(item => JSON.stringify(normalize(item))));
          const fresh = [];
          for (const item of checked) {
            const key = JSON.stringify(item);
            if (!existing.has(key)) { existing.add(key); fresh.push(item); }
          }
          if (request.result.length + fresh.length > LIMIT) {
            failure = new Error(`端末保存は${LIMIT}件までです。書き出してから不要な年表を削除してください。`);
            transaction.abort(); return;
          }
          try { serialize([...request.result, ...fresh]); }
          catch (exc) { failure = exc; transaction.abort(); return; }
          for (const item of fresh) store.add({...item, saved_at: new Date().toISOString()});
          added = fresh.length;
        };
        transaction.oncomplete = () => resolve(added);
        transaction.onerror = transaction.onabort = () => reject(failure || new Error("端末に保存できませんでした。容量やブラウザの保存設定を確認してください。"));
      });
    } finally { db.close(); }
  }
  async function remove(id) {
    const db = await open();
    try {
      await new Promise((resolve, reject) => {
        const transaction = db.transaction("timelines", "readwrite");
        transaction.objectStore("timelines").delete(id);
        transaction.oncomplete = resolve;
        transaction.onerror = transaction.onabort = () => reject(new Error("端末の年表を削除できませんでした。"));
      });
    } finally { db.close(); }
  }
  function download(records) {
    const body = serialize(records);
    const url = URL.createObjectURL(new Blob([body], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url; link.download = "timeline-generator-backup.json";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function importFile(file) {
    if (!file || file.size > MAX_BYTES) throw new Error("読み込める年表ファイルは8MiBまでです。");
    let data;
    try { data = JSON.parse(await file.text()); } catch { throw new Error("JSON形式の年表ファイルを選んでください。"); }
    if (data?.format !== FORMAT || data.version !== VERSION || !Array.isArray(data.timelines) || data.timelines.length > LIMIT) throw new Error("対応する年表バックアップではありません。");
    return save(data.timelines);
  }
  return {fromJob, list, save, remove, download, importFile};
})();

if (document.getElementById("local-list")) {
  const library = window.TimelineLibrary;
  const status = document.getElementById("local-status"), error = document.getElementById("local-error");
  const make = (tag, content, className) => {
    const element = document.createElement(tag); element.textContent = content || "";
    if (className) element.className = className;
    return element;
  };
  function fail(exc) { error.textContent = exc.message || "処理を完了できませんでした。"; error.hidden = false; }
  let records = [], busy = false;
  async function action(task) {
    if (busy) return;
    busy = true; error.hidden = true;
    document.querySelectorAll("main button, main input").forEach(element => { element.disabled = true; });
    try { await task(); } catch (exc) { fail(exc); }
    finally { busy = false; document.querySelectorAll("main button, main input").forEach(element => { element.disabled = false; }); }
  }
  async function refresh() {
    records = await library.list();
    const list = document.getElementById("local-list"); list.replaceChildren();
    document.getElementById("local-empty").hidden = records.length !== 0;
    document.getElementById("local-count").textContent = `このブラウザに${records.length}件保存（最大100件）`;
    for (const record of records.reverse()) {
      const details = make("details", "", "help-panel");
      details.append(make("summary", `${record.theme} · ${record.events.length}件`));
      const body = make("div", "", "info-body");
      body.append(make("p", `${record.period} · 生成日時 ${record.generated_at || "不明"}`, "help"));
      body.append(make("p", "保存・読み込みは内容や出典経路の正しさを認証しません。公開前に出典と利用条件を確認してください。", "help"));
      if (record.source_mode === "wikipedia") {
        const licence = make("p", "Wikipedia記事をもとに生成・再構成した本文。各出来事の出典を確認してください。 ", "help");
        const link = make("a", "CC BY-SA 4.0"); link.href = "https://creativecommons.org/licenses/by-sa/4.0/"; link.rel = "noopener noreferrer"; link.target = "_blank";
        licence.append(link); body.append(licence);
      }
      if (record.notice) body.append(make("p", record.notice, "help"));
      const timeline = make("ol", "", "timeline");
      for (const event of record.events) {
        const row = make("li", "", "event");
        row.append(make("div", event.date, "event-date"), make("h3", event.title, "event-title"), make("p", event.description, "event-description"));
        const link = make("a", "出典 ↗", "source-link"); link.href = event.source.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.title = event.source.title;
        row.append(link); timeline.append(row);
      }
      body.append(timeline);
      const tools = make("div", "", "job-actions");
      const download = make("button", "この年表を書き出す", "text-button"); download.type = "button";
      download.addEventListener("click", () => action(async () => library.download([record])));
      const remove = make("button", "端末から削除", "text-button"); remove.type = "button";
      remove.addEventListener("click", () => {
        if (!confirm(`「${record.theme}」をこのブラウザから削除しますか？必要なら先に書き出してください。`)) return;
        action(async () => { await library.remove(record.id); await refresh(); status.textContent = "端末の年表を削除しました。"; });
      });
      tools.append(download, remove); body.append(tools); details.append(body); list.append(details);
    }
  }
  document.getElementById("local-export").addEventListener("click", () => action(async () => library.download(await library.list())));
  document.getElementById("local-import").addEventListener("change", event => action(async () => {
    const file = event.target.files[0];
    if (!file) return;
    try { const added = await library.importFile(file); await refresh(); status.textContent = `${added}件を追加しました。同じ内容は重複保存しません。`; }
    finally { event.target.value = ""; }
  }));
  action(refresh);
}
