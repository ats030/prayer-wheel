"""usage-viewer: Claude Code / Codex 使用量ビューア (port 8516)

~/.claude/projects/**/*.jsonl と ~/.codex/sessions/**/*.jsonl を集計し、
日次・モデル別・プロジェクト別のトークン使用量を一覧表示する。
ファイル単位で mtime/size キャッシュするため、2回目以降の集計は差分のみ。
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

TZ = ZoneInfo("Asia/Tokyo")
CLAUDE_DIR = Path.home() / ".claude" / "projects"
CODEX_DIR = Path.home() / ".codex" / "sessions"

app = FastAPI()

_lock = threading.Lock()
_claude_cache: dict[str, dict] = {}  # path -> {mtime, size, entries}
_codex_cache: dict[str, dict] = {}   # path -> {mtime, size, parsed}


def _to_date(ts: str) -> str | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(TZ).strftime("%Y-%m-%d")


def _project_label(dirname: str) -> str:
    home = str(Path.home()).replace("/", "-")
    if dirname == home:
        return "~"
    if dirname.startswith(home + "-"):
        return "~/" + dirname[len(home) + 1:].replace("-", "/")
    return dirname.lstrip("-").replace("-", "/")


def _parse_claude_file(path: Path) -> list[dict]:
    entries = []
    project = _project_label(path.parent.name)
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            for line in fp:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = d.get("message") or {}
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                model = msg.get("model") or ""
                if not model or model == "<synthetic>":
                    continue
                date = _to_date(d.get("timestamp") or "")
                if not date:
                    continue
                msg_id = msg.get("id")
                key = f"{msg_id}:{d.get('requestId')}" if msg_id else None
                entries.append({
                    "key": key,
                    "date": date,
                    "model": model,
                    "project": project,
                    "input": usage.get("input_tokens") or 0,
                    "output": usage.get("output_tokens") or 0,
                    "cache_read": usage.get("cache_read_input_tokens") or 0,
                    "cache_create": usage.get("cache_creation_input_tokens") or 0,
                })
    except OSError:
        pass
    return entries


def _parse_codex_file(path: Path) -> dict:
    daily: dict[str, dict] = {}
    model = None
    cwd = None
    rate = None
    prev_total: dict | None = None
    keys = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            for line in fp:
                if '"token_count"' not in line and '"session_meta"' not in line \
                        and '"turn_context"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = d.get("type")
                payload = d.get("payload") or {}
                if kind == "session_meta":
                    cwd = payload.get("cwd") or cwd
                elif kind == "turn_context":
                    model = payload.get("model") or model
                elif kind == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    total = info.get("total_token_usage") or {}
                    date = _to_date(d.get("timestamp") or "")
                    rl = payload.get("rate_limits")
                    if rl and d.get("timestamp"):
                        rate = {"timestamp": d["timestamp"], **rl}
                    if not date or not total:
                        continue
                    if prev_total is None:
                        delta = {k: total.get(k) or 0 for k in keys}
                    else:
                        delta = {k: (total.get(k) or 0) - (prev_total.get(k) or 0)
                                 for k in keys}
                        if delta["total_tokens"] < 0:  # セッション途中のリセット
                            delta = {k: (info.get("last_token_usage") or {}).get(k) or 0
                                     for k in keys}
                    prev_total = total
                    agg = daily.setdefault(date, {k: 0 for k in keys})
                    for k in keys:
                        agg[k] += max(delta[k], 0)
    except OSError:
        pass
    return {"daily": daily, "model": model or "unknown", "cwd": cwd, "rate": rate}


def _refresh_cache(cache: dict, paths: list[Path], parser) -> None:
    alive = set()
    for path in paths:
        try:
            st = path.stat()
        except OSError:
            continue
        key = str(path)
        alive.add(key)
        cached = cache.get(key)
        if cached and cached["mtime"] == st.st_mtime and cached["size"] == st.st_size:
            continue
        cache[key] = {"mtime": st.st_mtime, "size": st.st_size, "data": parser(path)}
    for key in list(cache):
        if key not in alive:
            del cache[key]


def _add(agg: dict, key: str, fields: dict) -> None:
    row = agg.setdefault(key, {k: 0 for k in fields})
    for k, v in fields.items():
        row[k] += v


def collect() -> dict:
    with _lock:
        _refresh_cache(_claude_cache, sorted(CLAUDE_DIR.glob("*/*.jsonl")),
                       _parse_claude_file)
        _refresh_cache(_codex_cache, sorted(CODEX_DIR.rglob("*.jsonl")),
                       _parse_codex_file)

        c_daily: dict[str, dict] = {}
        c_models: dict[str, dict] = {}
        c_projects: dict[str, dict] = {}
        seen: set[str] = set()
        for cached in _claude_cache.values():
            for e in cached["data"]:
                if e["key"]:
                    if e["key"] in seen:
                        continue
                    seen.add(e["key"])
                fields = {"input": e["input"], "output": e["output"],
                          "cache_read": e["cache_read"],
                          "cache_create": e["cache_create"]}
                _add(c_daily, e["date"], fields)
                _add(c_models, e["model"], fields)
                _add(c_projects, e["project"], fields)

        x_daily: dict[str, dict] = {}
        x_models: dict[str, dict] = {}
        x_projects: dict[str, dict] = {}
        rate = None
        for cached in _codex_cache.values():
            parsed = cached["data"]
            session_total: dict[str, int] = {}
            for date, row in parsed["daily"].items():
                fields = {"input": row["input_tokens"],
                          "cached_input": row["cached_input_tokens"],
                          "output": row["output_tokens"],
                          "total": row["total_tokens"]}
                _add(x_daily, date, fields)
                for k, v in fields.items():
                    session_total[k] = session_total.get(k, 0) + v
            if session_total:
                _add(x_models, parsed["model"], session_total)
                if parsed["cwd"]:
                    label = parsed["cwd"].replace(str(Path.home()), "~")
                    _add(x_projects, label, session_total)
            r = parsed["rate"]
            if r and (rate is None or r["timestamp"] > rate["timestamp"]):
                rate = r

        return {
            "generated_at": datetime.now(TZ).isoformat(),
            "claude": {"daily": c_daily, "models": c_models, "projects": c_projects},
            "codex": {"daily": x_daily, "models": x_models, "projects": x_projects,
                      "rate_limits": rate},
        }


@app.on_event("startup")
def warm_cache() -> None:
    threading.Thread(target=collect, daemon=True).start()


@app.get("/api/usage")
def api_usage() -> JSONResponse:
    return JSONResponse(collect())


@app.get("/favicon.ico")
def favicon() -> Response:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           '<text x="32" y="45" text-anchor="middle" font-family="Apple Color Emoji,'
           'Segoe UI Emoji,Noto Color Emoji,sans-serif" font-size="39">🧮</text></svg>')
    return Response(content=svg, media_type="image/svg+xml")


PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI使用量</title>
<link rel="icon" href="/favicon.ico">
<style>
:root {
  --canvas: #010102; --surface-1: #0f1011; --surface-2: #141516;
  --surface-3: #18191a; --hairline: #23252a; --hairline-strong: #34343a;
  --ink: #f7f8f8; --ink-muted: #d0d6e0; --ink-subtle: #8a8f98;
  --accent: #5e6ad2;
  --series-claude: #3987e5; --series-codex: #008300;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: var(--canvas); color: var(--ink);
  font-family: Inter, "SF Pro Display", -apple-system, system-ui, "Segoe UI",
    "Hiragino Sans", "Noto Sans CJK JP", sans-serif;
  font-size: 16px; line-height: 1.5; letter-spacing: -0.05px;
  padding: 24px 16px 64px;
}
.wrap { max-width: 1080px; margin: 0 auto; }
header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
h1 { font-size: 28px; font-weight: 600; letter-spacing: -0.6px; }
.updated { color: var(--ink-subtle); font-size: 12px; }
h2 { font-size: 15px; font-weight: 500; letter-spacing: -0.2px;
     color: var(--ink-muted); margin-bottom: 12px; }
.section { margin-top: 32px; }
.card { background: var(--surface-1); border: 1px solid var(--hairline);
        border-radius: 12px; padding: 24px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px; margin-top: 24px; }
.kpi { background: var(--surface-1); border: 1px solid var(--hairline);
       border-radius: 12px; padding: 16px 20px; }
.kpi .label { font-size: 13px; font-weight: 500; letter-spacing: 0.4px;
              color: var(--ink-subtle); }
.kpi .value { font-size: 28px; font-weight: 600; letter-spacing: -0.6px;
              margin: 4px 0 8px; }
.kpi .split { display: flex; flex-direction: column; gap: 2px;
              font-size: 13px; color: var(--ink-muted); }
.chip { display: inline-block; width: 10px; height: 10px; border-radius: 3px;
        margin-right: 6px; vertical-align: baseline; }
.chip.claude { background: var(--series-claude); }
.chip.codex { background: var(--series-codex); }
.meter { height: 6px; background: var(--surface-3); border-radius: 9999px;
         overflow: hidden; margin-top: 8px; }
.meter > div { height: 100%; background: var(--series-codex); border-radius: 9999px; }
.toolbar { display: flex; align-items: center; justify-content: space-between;
           flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
.tabs { display: flex; gap: 4px; }
.tab { background: transparent; color: var(--ink-subtle); border: none;
       font: inherit; font-size: 14px; font-weight: 500; padding: 6px 14px;
       border-radius: 9999px; cursor: pointer; }
.tab:hover { color: var(--ink); }
.tab.selected { background: var(--surface-2); color: var(--ink); }
.tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.legend { display: flex; gap: 16px; font-size: 13px; color: var(--ink-muted); }
#chart-box { position: relative; }
#chart { width: 100%; display: block; }
#tooltip { position: absolute; pointer-events: none; display: none;
           background: var(--surface-3); border: 1px solid var(--hairline-strong);
           border-radius: 8px; padding: 8px 12px; font-size: 13px;
           color: var(--ink-muted); white-space: nowrap; z-index: 2; }
#tooltip .tt-date { color: var(--ink); font-weight: 500; margin-bottom: 2px; }
.cards-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.cards-2 > .card { min-width: 0; }
@media (max-width: 768px) { .cards-2 { grid-template-columns: 1fr; } }
.table-box { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 8px 12px; text-align: right; white-space: nowrap;
         border-bottom: 1px solid var(--hairline); }
th { color: var(--ink-subtle); font-weight: 500; }
td { color: var(--ink-muted); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
td:first-child { color: var(--ink); }
tr:last-child td { border-bottom: none; }
.status { color: var(--ink-subtle); font-size: 14px; padding: 48px 0;
          text-align: center; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🧮 AI使用量</h1>
    <span class="updated" id="updated"></span>
  </header>
  <div class="updated">Claude Code と Codex のトークン使用量(ローカルログ集計)</div>

  <div id="loading" class="status">読み込み中…</div>
  <div id="content" style="display:none">
    <div class="kpis" id="kpis"></div>

    <div class="section card">
      <div class="toolbar">
        <h2 style="margin:0">日次トークン使用量</h2>
        <div class="tabs" id="range-tabs" role="tablist"></div>
        <div class="legend">
          <span><span class="chip claude"></span>Claude Code</span>
          <span><span class="chip codex"></span>Codex</span>
        </div>
      </div>
      <div id="chart-box">
        <svg id="chart" height="260" role="img" aria-label="日次トークン使用量の積み上げ棒グラフ"></svg>
        <div id="tooltip"></div>
      </div>
    </div>

    <div class="section cards-2">
      <div class="card">
        <h2><span class="chip claude"></span>Claude Code モデル別</h2>
        <div class="table-box" id="claude-models"></div>
      </div>
      <div class="card">
        <h2><span class="chip codex"></span>Codex モデル別</h2>
        <div class="table-box" id="codex-models"></div>
      </div>
    </div>

    <div class="section cards-2">
      <div class="card">
        <h2><span class="chip claude"></span>Claude Code プロジェクト別</h2>
        <div class="table-box" id="claude-projects"></div>
      </div>
      <div class="card">
        <h2><span class="chip codex"></span>Codex 作業ディレクトリ別</h2>
        <div class="table-box" id="codex-projects"></div>
      </div>
    </div>

    <div class="section card">
      <h2>日次内訳</h2>
      <div class="table-box" id="daily-table"></div>
    </div>
  </div>
</div>

<script>
let DATA = null;
let RANGE = 30;

const fmt = n => n.toLocaleString("ja-JP");
const abbr = n => {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
};
const claudeTotal = r => r.input + r.output + r.cache_read + r.cache_create;

function lastDates(n) {
  const out = [];
  const d = new Date();
  for (let i = n - 1; i >= 0; i--) {
    const t = new Date(d.getTime() - i * 86400000);
    out.push(t.toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" }));
  }
  return out;
}

function seriesFor(dates) {
  return dates.map(date => {
    const c = DATA.claude.daily[date];
    const x = DATA.codex.daily[date];
    return { date, claude: c ? claudeTotal(c) : 0, codex: x ? x.total : 0 };
  });
}

function renderKpis() {
  const box = document.getElementById("kpis");
  box.innerHTML = "";
  for (const [label, n] of [["今日", 1], ["過去7日", 7], ["過去30日", 30]]) {
    const rows = seriesFor(lastDates(n));
    const c = rows.reduce((a, r) => a + r.claude, 0);
    const x = rows.reduce((a, r) => a + r.codex, 0);
    const el = document.createElement("div");
    el.className = "kpi";
    el.innerHTML = `<div class="label">${label}</div>` +
      `<div class="value" title="${fmt(c + x)} tokens">${abbr(c + x)}</div>` +
      `<div class="split">` +
      `<span><span class="chip claude"></span>Claude Code ${abbr(c)}</span>` +
      `<span><span class="chip codex"></span>Codex ${abbr(x)}</span></div>`;
    box.appendChild(el);
  }
  const rl = DATA.codex.rate_limits;
  if (rl && rl.primary) {
    const pct = Math.round(rl.primary.used_percent);
    const days = Math.round((rl.primary.window_minutes || 0) / 1440);
    const reset = rl.primary.resets_at
      ? new Date(rl.primary.resets_at * 1000).toLocaleDateString("ja-JP",
          { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" })
      : null;
    const el = document.createElement("div");
    el.className = "kpi";
    el.innerHTML = `<div class="label">CODEX リミット (${days}日枠)</div>` +
      `<div class="value">${pct}%</div>` +
      `<div class="split"><span>${reset ? reset + " リセット · " : ""}` +
      `plan: ${rl.plan_type || "?"}</span></div>` +
      `<div class="meter"><div style="width:${Math.min(pct, 100)}%"></div></div>`;
    box.appendChild(el);
  }
}

function roundedTop(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y}` +
    ` L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`;
}

function renderChart() {
  const svg = document.getElementById("chart");
  const tooltip = document.getElementById("tooltip");
  const dates = lastDates(RANGE);
  const rows = seriesFor(dates);
  const W = svg.clientWidth || 800, H = 260;
  const m = { top: 8, right: 8, bottom: 24, left: 48 };
  const pw = W - m.left - m.right, ph = H - m.top - m.bottom;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const max = Math.max(1, ...rows.map(r => r.claude + r.codex));
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const yMax = Math.ceil(max / step) * step;
  const band = pw / rows.length;
  const bw = Math.max(3, Math.min(band * 0.6, 28));
  const y = v => m.top + ph - (v / yMax) * ph;
  let g = "";
  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i, yy = y(v);
    g += `<line x1="${m.left}" y1="${yy}" x2="${W - m.right}" y2="${yy}"` +
      ` stroke="${i === 0 ? "#34343a" : "#23252a"}" stroke-width="1"/>`;
    g += `<text x="${m.left - 8}" y="${yy + 4}" text-anchor="end"` +
      ` fill="#8a8f98" font-size="11">${abbr(v)}</text>`;
  }
  const labelEvery = Math.ceil(rows.length / 10);
  rows.forEach((r, i) => {
    const cx = m.left + band * i + band / 2;
    const x0 = cx - bw / 2;
    const hC = (r.claude / yMax) * ph, hX = (r.codex / yMax) * ph;
    const gap = hC > 0 && hX > 0 ? 2 : 0;
    if (hC > 0) {
      const yc = y(r.claude);
      g += hX > 0
        ? `<rect x="${x0}" y="${yc}" width="${bw}" height="${hC}" fill="#3987e5"/>`
        : `<path d="${roundedTop(x0, yc, bw, hC, 4)}" fill="#3987e5"/>`;
    }
    if (hX > 0) {
      const yx = y(r.claude + r.codex);
      const hh = Math.max(hX - gap, 1);
      g += `<path d="${roundedTop(x0, yx, bw, hh, 4)}" fill="#008300"/>`;
    }
    if (i % labelEvery === 0) {
      const [, mo, da] = r.date.split("-");
      g += `<text x="${cx}" y="${H - 6}" text-anchor="middle" fill="#8a8f98"` +
        ` font-size="11">${Number(mo)}/${Number(da)}</text>`;
    }
    g += `<rect class="hit" data-i="${i}" x="${m.left + band * i}" y="${m.top}"` +
      ` width="${band}" height="${ph}" fill="transparent"/>`;
  });
  svg.innerHTML = g;
  svg.querySelectorAll(".hit").forEach(hit => {
    hit.addEventListener("mousemove", ev => {
      const r = rows[Number(hit.dataset.i)];
      tooltip.innerHTML = `<div class="tt-date">${r.date}</div>` +
        `<div><span class="chip claude"></span>Claude Code ${fmt(r.claude)}</div>` +
        `<div><span class="chip codex"></span>Codex ${fmt(r.codex)}</div>` +
        `<div>合計 ${fmt(r.claude + r.codex)}</div>`;
      tooltip.style.display = "block";
      const box = document.getElementById("chart-box").getBoundingClientRect();
      let tx = ev.clientX - box.left + 14, ty = ev.clientY - box.top - 10;
      if (tx + tooltip.offsetWidth > box.width) tx -= tooltip.offsetWidth + 28;
      tooltip.style.left = tx + "px";
      tooltip.style.top = ty + "px";
    });
    hit.addEventListener("mouseleave", () => { tooltip.style.display = "none"; });
  });
}

function renderRangeTabs() {
  const box = document.getElementById("range-tabs");
  box.innerHTML = "";
  for (const n of [7, 30, 90]) {
    const b = document.createElement("button");
    b.className = "tab" + (n === RANGE ? " selected" : "");
    b.textContent = `${n}日`;
    b.addEventListener("click", () => { RANGE = n; renderRangeTabs(); renderChart(); });
    box.appendChild(b);
  }
}

function makeTable(headers, rows) {
  const th = headers.map(h => `<th>${h}</th>`).join("");
  const trs = rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
}

function renderTables() {
  const cm = Object.entries(DATA.claude.models)
    .sort((a, b) => claudeTotal(b[1]) - claudeTotal(a[1]));
  document.getElementById("claude-models").innerHTML = makeTable(
    ["モデル", "入力", "出力", "キャッシュ読取", "キャッシュ作成", "計"],
    cm.map(([k, v]) => [k, fmt(v.input), fmt(v.output), fmt(v.cache_read),
                        fmt(v.cache_create), fmt(claudeTotal(v))]));

  const xm = Object.entries(DATA.codex.models).sort((a, b) => b[1].total - a[1].total);
  document.getElementById("codex-models").innerHTML = makeTable(
    ["モデル", "入力", "(内キャッシュ)", "出力", "計"],
    xm.map(([k, v]) => [k, fmt(v.input), fmt(v.cached_input), fmt(v.output),
                        fmt(v.total)]));

  const cp = Object.entries(DATA.claude.projects)
    .sort((a, b) => claudeTotal(b[1]) - claudeTotal(a[1]));
  document.getElementById("claude-projects").innerHTML = makeTable(
    ["プロジェクト", "入力", "出力", "計"],
    cp.map(([k, v]) => [k, fmt(v.input), fmt(v.output), fmt(claudeTotal(v))]));

  const xp = Object.entries(DATA.codex.projects).sort((a, b) => b[1].total - a[1].total);
  document.getElementById("codex-projects").innerHTML = makeTable(
    ["ディレクトリ", "入力", "出力", "計"],
    xp.map(([k, v]) => [k, fmt(v.input), fmt(v.output), fmt(v.total)]));

  const dates = new Set([...Object.keys(DATA.claude.daily),
                         ...Object.keys(DATA.codex.daily)]);
  const days = [...dates].sort().reverse().slice(0, 90);
  document.getElementById("daily-table").innerHTML = makeTable(
    ["日付", "Claude 入力", "Claude 出力", "Claude キャッシュ", "Claude 計",
     "Codex 計", "合計"],
    days.map(date => {
      const c = DATA.claude.daily[date] || { input: 0, output: 0, cache_read: 0, cache_create: 0 };
      const x = DATA.codex.daily[date] || { total: 0 };
      return [date, fmt(c.input), fmt(c.output), fmt(c.cache_read + c.cache_create),
              fmt(claudeTotal(c)), fmt(x.total), fmt(claudeTotal(c) + x.total)];
    }));
}

async function load() {
  try {
    const res = await fetch("/api/usage");
    DATA = await res.json();
  } catch (e) {
    document.getElementById("loading").textContent = "読み込みに失敗しました: " + e;
    return;
  }
  document.getElementById("loading").style.display = "none";
  document.getElementById("content").style.display = "";
  document.getElementById("updated").textContent =
    "更新: " + new Date(DATA.generated_at).toLocaleString("ja-JP",
      { timeZone: "Asia/Tokyo" });
  renderKpis();
  renderRangeTabs();
  renderChart();
  renderTables();
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  if (!DATA) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderChart, 150);
});
load();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8516)
