"""visit-log: 自作アプリのアクセス解析 (port 8526)

各アプリのページに 1行のタグを入れると、閲覧が 1x1 GIF ビーコンとして
このサービスに届く。GA4 と違い外部へ何も送らず、生ログは手元だけに残る。

計測点はここ 1 箇所。各アプリ側にはコードを持たせない (タグ 1 行だけ)。
イベントは ~/data/visit-log/events-YYYY-MM.jsonl に 1 行 1 件で追記する。
再パースで作り直せない生データなので ~/data に置く (~/CLAUDE.md「データの保全」)。
集計は起動中だけ持てばよいのでメモリキャッシュ、対応表の類は ~/cache。

プライバシー:
  IP と User-Agent は保存しない。訪問者の区別は
  sha256(永続ソルト + その日の日付 + IP + UA)[:16] だけを残す。
  日付が変わると同じ人でも別 ID になるので、日次のユニーク数は数えられるが
  日をまたいだ個人の追跡はできない。DNT / Sec-GPC が立っていれば記録しない。
"""

import hashlib
import json
import os
import re
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

TZ = ZoneInfo("Asia/Tokyo")
DATA_DIR = Path.home() / "data" / "visit-log"
CACHE_DIR = Path.home() / "cache" / "visit-log"
SALT_PATH = DATA_DIR / "salt"
PORT = int(os.environ.get("VISIT_LOG_PORT", "8526"))

# 1x1 透過 GIF。タグが img で読むのでこれを返す。
PIXEL = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000"
    "010001000002024401003b"
)

# 受け付ける値の上限。ログを膨らませないためと、UI に長い文字列を出さないため。
MAX_SITE = 64
MAX_PATH = 300
MAX_REF = 300
SITE_RE = re.compile(r"^[A-Za-z0-9._-]{1,%d}$" % MAX_SITE)
# 計測対象として登録した URL の一覧。イベントが 1 件も来ていないサイトも
# 「登録したのに届いていない」として画面に出したいので、イベントとは別に持つ。
SITES_PATH = DATA_DIR / "sites.json"
MAX_URL = 300
MAX_NOTE = 120
URL_RE = re.compile(r"^https?://[^\s/?#]+")

_lock = threading.Lock()
# 登録簿は読んで書き戻すので、同時登録で片方が消えないよう別ロックで囲う。
_sites_lock = threading.Lock()
_salt: str | None = None
_cache: dict = {"mtimes": {}, "events": []}


def salt() -> str:
    """訪問者 ID 用の永続ソルト。無ければ作る。

    再起動で変わると同じ日の同じ人が別 ID に割れてユニーク数が水増しされるので
    ファイルに残す。漏れると IP の総当たりで ID を復元されうるため 0600。
    """
    global _salt
    if _salt is None:
        if SALT_PATH.exists():
            _salt = SALT_PATH.read_text().strip()
        else:
            _salt = secrets.token_hex(32)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SALT_PATH.write_text(_salt)
            SALT_PATH.chmod(0o600)
    return _salt


def visitor_id(ip: str, ua: str, day: str) -> str:
    h = hashlib.sha256(f"{salt()}|{day}|{ip}|{ua}".encode()).hexdigest()
    return h[:16]


def client_ip(request: Request) -> str:
    # Funnel や nginx を挟むと peer は 127.0.0.1 になる。前段が付ける
    # X-Forwarded-For の先頭が実際の送信元。前段が無いときは peer をそのまま使う。
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def device_class(ua: str) -> str:
    """UA は保存しないので、粒度をここまで落として 1 語だけ残す。"""
    u = ua.lower()
    if "bot" in u or "crawler" in u or "spider" in u or "headless" in u:
        return "bot"
    if "ipad" in u or "tablet" in u:
        return "tablet"
    if "mobi" in u or "android" in u or "iphone" in u:
        return "mobile"
    if not u:
        return "unknown"
    return "desktop"


def clean(value: str, limit: int) -> str:
    value = (value or "").strip().replace("\n", " ").replace("\r", " ")
    return value[:limit]


def ref_host(ref: str) -> str:
    """リファラはホストだけ残す。パスやクエリには他サイトの個人情報が乗りうる。"""
    m = re.match(r"^https?://([^/?#]+)", ref or "")
    return m.group(1)[:100] if m else ""


def load_sites() -> list[dict]:
    if not SITES_PATH.exists():
        return []
    try:
        data = json.loads(SITES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [r for r in data if isinstance(r, dict) and r.get("name")] if isinstance(data, list) else []


def save_sites(sites: list[dict]) -> None:
    """書き込み中に読まれても壊れないよう、別名に書いてから置き換える。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SITES_PATH.with_name("sites.json.tmp")
    tmp.write_text(json.dumps(sites, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SITES_PATH)


def log_path(dt: datetime) -> Path:
    return DATA_DIR / f"events-{dt:%Y-%m}.jsonl"


def record(request: Request, site: str, path: str, ref: str) -> None:
    if request.headers.get("dnt") == "1" or request.headers.get("sec-gpc") == "1":
        return
    if not SITE_RE.match(site or ""):
        return
    now = datetime.now(TZ)
    ua = request.headers.get("user-agent", "")
    row = {
        "ts": now.isoformat(timespec="seconds"),
        "site": site,
        "path": clean(path, MAX_PATH) or "/",
        "ref": ref_host(clean(ref, MAX_REF)),
        "vid": visitor_id(client_ip(request), ua, f"{now:%Y-%m-%d}"),
        "dev": device_class(ua),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        with log_path(now).open("a", encoding="utf-8") as fh:
            fh.write(line)


def load_events(days: int) -> list[dict]:
    """必要な月のファイルだけ読む。mtime と size が変わらない月は読み直さない。"""
    now = datetime.now(TZ)
    since = now - timedelta(days=days)
    months, cur = [], since.replace(day=1)
    while cur <= now:
        months.append(f"{cur:%Y-%m}")
        cur = (cur.replace(day=28) + timedelta(days=7)).replace(day=1)

    with _lock:
        stale = False
        for month in months:
            fp = DATA_DIR / f"events-{month}.jsonl"
            stat = fp.stat() if fp.exists() else None
            key = (stat.st_mtime, stat.st_size) if stat else None
            if _cache["mtimes"].get(month) != key:
                _cache["mtimes"][month] = key
                stale = True
        if stale:
            events = []
            for month in months:
                fp = DATA_DIR / f"events-{month}.jsonl"
                if not fp.exists():
                    continue
                for line in fp.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # 追記が途中で切れた行は捨てる
            _cache["events"] = events
        events = _cache["events"]

    cutoff = since.isoformat(timespec="seconds")
    return [e for e in events if e.get("ts", "") >= cutoff]


def summarize(days: int, include_bots: bool) -> dict:
    events = load_events(days)
    if not include_bots:
        events = [e for e in events if e.get("dev") != "bot"]

    daily = defaultdict(lambda: {"views": 0, "vids": set()})
    sites = defaultdict(lambda: {"views": 0, "vids": set()})
    paths = defaultdict(int)
    refs = defaultdict(int)
    devs = defaultdict(int)
    hours = defaultdict(int)
    last_seen: dict[str, str] = {}

    for e in events:
        day = e.get("ts", "")[:10]
        vid = e.get("vid", "")
        site = e.get("site", "?")
        daily[day]["views"] += 1
        daily[day]["vids"].add(vid)
        sites[site]["views"] += 1
        sites[site]["vids"].add(vid)
        paths[f"{site}{e.get('path', '/')}"] += 1
        if e.get("ref"):
            refs[e["ref"]] += 1
        devs[e.get("dev", "unknown")] += 1
        hours[e.get("ts", "")[11:13]] += 1
        ts = e.get("ts", "")
        if ts > last_seen.get(site, ""):
            last_seen[site] = ts

    registered = {r["name"]: r for r in load_sites()}

    def top(counter, limit=20):
        items = sorted(counter.items(), key=lambda kv: -kv[1])[:limit]
        return [{"key": k, "views": v} for k, v in items]

    return {
        "days": days,
        "total_views": len(events),
        "total_visitors": len({e.get("vid") for e in events}),
        "daily": [
            {"date": d, "views": v["views"], "visitors": len(v["vids"])}
            for d, v in sorted(daily.items())
        ],
        # 登録済みで未計測のサイトは 0 件として残す。届いていないこと自体が
        # 見たい情報 (タグの入れ忘れか、そのページに誰も来ていないか) なので消さない。
        "sites": sorted(
            (
                {
                    "key": name,
                    "views": sites[name]["views"] if name in sites else 0,
                    "visitors": len(sites[name]["vids"]) if name in sites else 0,
                    "url": registered.get(name, {}).get("url", ""),
                    "note": registered.get(name, {}).get("note", ""),
                    "registered": name in registered,
                    "last_seen": last_seen.get(name, ""),
                }
                for name in set(sites) | set(registered)
            ),
            key=lambda r: (-r["views"], r["key"]),
        ),
        "paths": top(paths),
        "refs": top(refs),
        "devices": top(devs, 10),
        "hours": [{"key": f"{h:02d}", "views": hours.get(f"{h:02d}", 0)} for h in range(24)],
    }


app = FastAPI(title="visit-log", docs_url=None, redoc_url=None, openapi_url=None)

NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/px.gif")
async def pixel(request: Request, s: str = "", p: str = "/", r: str = ""):
    """画像ビーコン。img で読ませるのでクロスオリジンでも CORS が要らない。"""
    record(request, s, p, r)
    return Response(content=PIXEL, media_type="image/gif", headers=NO_STORE)


@app.get("/v.js")
async def tag():
    """各アプリが読み込む計測タグ。data-site で名前を渡す。

    埋め込み側は次の 1 行だけ:
      <script src="http://ubuntu-server-app:8526/v.js" data-site="rss-reader" defer></script>
    """
    js = """(function(){
  var el = document.currentScript;
  if (!el) return;
  if (navigator.doNotTrack === "1" || navigator.globalPrivacyControl) return;
  var site = el.getAttribute("data-site") || location.hostname;
  var base = el.src.replace(/\\/v\\.js.*$/, "");
  function hit(){
    var u = base + "/px.gif?s=" + encodeURIComponent(site)
          + "&p=" + encodeURIComponent(location.pathname)
          + "&r=" + encodeURIComponent(document.referrer)
          + "&_=" + Date.now();
    new Image().src = u;
  }
  hit();
  // SPA の画面遷移も 1 ページとして数える。history を差し替えず popstate と
  // pushState のラップだけにして、他スクリプトの挙動を変えない。
  var push = history.pushState;
  history.pushState = function(){ push.apply(this, arguments); hit(); };
  addEventListener("popstate", hit);
})();"""
    return Response(
        content=js,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/api/sites")
async def api_sites_list():
    return JSONResponse(load_sites(), headers=NO_STORE)


@app.post("/api/sites")
async def api_sites_add(request: Request):
    # クロスサイトの単純フォーム送信は application/json を名乗れない。
    # Tailnet 内の別ページから勝手に登録されるのをここで止める。
    if "application/json" not in request.headers.get("content-type", ""):
        return JSONResponse({"error": "JSON で送ってください"}, status_code=415, headers=NO_STORE)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "JSON を読めませんでした"}, status_code=400, headers=NO_STORE)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON を読めませんでした"}, status_code=400, headers=NO_STORE)

    name = clean(str(body.get("name", "")), MAX_SITE)
    url = clean(str(body.get("url", "")), MAX_URL)
    note = clean(str(body.get("note", "")), MAX_NOTE)
    if not SITE_RE.match(name):
        return JSONResponse(
            {"error": "名前は英数字と . _ - だけで 64 文字までです"}, status_code=400, headers=NO_STORE
        )
    if not URL_RE.match(url):
        return JSONResponse(
            {"error": "URL は http:// か https:// で始めてください"}, status_code=400, headers=NO_STORE
        )

    row = {"name": name, "url": url, "note": note, "added": datetime.now(TZ).isoformat(timespec="seconds")}
    with _sites_lock:
        sites = load_sites()
        for i, r in enumerate(sites):
            if r.get("name") == name:
                row["added"] = r.get("added", row["added"])  # 同じ名前は上書き。登録日は残す
                sites[i] = row
                break
        else:
            sites.append(row)
        save_sites(sites)
    return JSONResponse(row, headers=NO_STORE)


@app.delete("/api/sites/{name}")
async def api_sites_delete(name: str):
    """登録簿から外すだけで、記録済みのイベントは消さない。"""
    with _sites_lock:
        sites = load_sites()
        kept = [r for r in sites if r.get("name") != name]
        if len(kept) == len(sites):
            return JSONResponse({"error": "登録されていません"}, status_code=404, headers=NO_STORE)
        save_sites(kept)
    return JSONResponse({"deleted": name}, headers=NO_STORE)


@app.get("/api/summary")
async def api_summary(days: int = 30, bots: int = 0):
    days = max(1, min(days, 400))
    return JSONResponse(summarize(days, include_bots=bool(bots)), headers=NO_STORE)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "port": PORT}, headers=NO_STORE)


@app.get("/", response_class=HTMLResponse)
async def index():
    return Response(content=INDEX_HTML, media_type="text/html; charset=utf-8", headers=NO_STORE)


INDEX_HTML = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>visit-log</title>
<style>
:root{--bg:#fbfbfa;--fg:#1c1c1a;--mut:#6b6b66;--line:#e2e2dd;--card:#fff;--acc:#2f6f4f}
@media(prefers-color-scheme:dark){:root{--bg:#16171a;--fg:#e8e8e4;--mut:#9a9a94;--line:#2c2e33;--card:#1e2024;--acc:#6bbf8f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,-apple-system,"Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px;letter-spacing:.02em}
.sub{color:var(--mut);font-size:13px;margin:0 0 20px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:20px}
button{font:inherit;padding:5px 12px;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .n{font-size:26px;font-weight:600;letter-spacing:-.01em}
.kpi .l{color:var(--mut);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px;overflow-x:auto}
.card h2{font-size:13px;margin:0 0 12px;color:var(--mut);font-weight:600;letter-spacing:.06em;text-transform:uppercase}
table{border-collapse:collapse;width:100%;min-width:320px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
th{color:var(--mut);font-weight:500;font-size:12px}
td.n,th.n{text-align:right}
.k{max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chart{display:flex;align-items:flex-end;gap:2px;height:120px}
.chart div{flex:1;background:var(--acc);border-radius:2px 2px 0 0;min-height:1px;opacity:.85}
.chart div:hover{opacity:1}
.empty{color:var(--mut);padding:8px 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
code{background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:12px}
a{color:var(--acc)}
.reg{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.reg input{font:inherit;padding:5px 10px;border:1px solid var(--line);background:var(--bg);color:var(--fg);border-radius:6px;flex:1;min-width:150px}
.msg{padding:6px 10px;border-radius:6px;margin-bottom:10px;font-size:13px;background:var(--bg);border:1px solid var(--line)}
.msg.err{color:#b3261e;border-color:#b3261e}
@media(prefers-color-scheme:dark){.msg.err{color:#ff8a80;border-color:#8c3b34}}
button.link{border:none;background:none;color:var(--acc);padding:2px 6px;text-decoration:underline;border-radius:0}
.badge{font-size:11px;color:var(--mut);border:1px solid var(--line);border-radius:999px;padding:0 6px;margin-left:6px}
</style></head><body><div class="wrap">
<h1>visit-log</h1>
<p class="sub">自作アプリのアクセス集計。外部へは何も送らず、生ログは <code>~/data/visit-log/</code> だけに残ります。</p>
<div class="bar">
  <span style="color:var(--mut);font-size:12px">期間</span>
  <button data-d="7">7日</button><button data-d="30" class="on">30日</button><button data-d="90">90日</button>
  <span style="width:12px"></span>
  <button id="bots">botを含める</button>
</div>
<div class="kpis" id="kpis"></div>
<div class="card"><h2>日次 ページビュー</h2><div class="chart" id="chart"></div><div id="range" style="color:var(--mut);font-size:12px;display:flex;justify-content:space-between;margin-top:6px"></div></div>
<div class="card"><h2>計測対象</h2>
<p style="margin:0 0 10px;color:var(--mut)">登録しておくと、まだ 1 件も届いていないサイトも一覧に残ります (タグの入れ忘れに気づけます)。</p>
<form class="reg" id="reg">
  <input id="f-name" placeholder="名前 (例 rss-reader)" maxlength="64" required>
  <input id="f-url" placeholder="https://..." maxlength="300" required>
  <input id="f-note" placeholder="メモ (任意)" maxlength="120">
  <button type="submit">登録</button>
</form>
<div id="reg-msg" class="msg" hidden></div>
<div id="sites"></div>
<p style="margin:14px 0 8px;color:var(--mut)">計測したいページの <code>&lt;/body&gt;</code> の直前に1行入れます。行の「タグ」を押すとそのサイト用に切り替わります。</p>
<code id="snippet"></code></div>
<div class="grid2">
  <div class="card"><h2>時間帯</h2><div class="chart" id="hours"></div></div>
  <div class="card"><h2>ページ</h2><div id="paths"></div></div>
  <div class="card"><h2>参照元</h2><div id="refs"></div></div>
  <div class="card"><h2>デバイス</h2><div id="devices"></div></div>
</div>
</div>
<script>
let days = 30, bots = 0;
const num = n => n.toLocaleString("ja-JP");

function table(rows, label) {
  if (!rows.length) return '<div class="empty">まだ記録がありません</div>';
  const body = rows.map(r =>
    `<tr><td class="k">${esc(r.key)}</td><td class="n">${num(r.views)}</td></tr>`).join("");
  return `<table><tr><th>${label}</th><th class="n">PV</th></tr>${body}</table>`;
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function bars(el, rows, labelFn) {
  const max = Math.max(1, ...rows.map(r => r.views));
  el.innerHTML = rows.map(r =>
    `<div style="height:${(r.views / max * 100).toFixed(1)}%" title="${esc(labelFn(r))}: ${num(r.views)}"></div>`).join("");
}

function sitesTable(rows) {
  if (!rows.length) return '<div class="empty">まだ登録も記録もありません</div>';
  const body = rows.map(r => `<tr>
    <td class="k">${esc(r.key)}${r.registered ? "" : '<span class="badge">未登録</span>'}</td>
    <td class="k">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url)}</a>` : ""}`
    + `${r.note ? `<div style="color:var(--mut);font-size:12px">${esc(r.note)}</div>` : ""}</td>
    <td class="n">${num(r.views)}</td>
    <td class="n">${num(r.visitors)}</td>
    <td class="k" style="color:var(--mut);font-size:12px">${r.last_seen ? esc(r.last_seen.slice(0, 16).replace("T", " ")) : "未着"}</td>
    <td class="n"><button class="link" data-tag="${esc(r.key)}">タグ</button>`
    + `${r.registered ? `<button class="link" data-del="${esc(r.key)}">削除</button>` : ""}</td></tr>`).join("");
  return `<table><tr><th>名前</th><th>URL / メモ</th><th class="n">PV</th><th class="n">訪問者</th><th>最終記録</th><th></th></tr>${body}</table>`;
}

const showTag = name =>
  document.getElementById("snippet").textContent =
    `<script src="${location.origin}/v.js" data-site="${name}" defer><\\/script>`;

function msg(text, isErr) {
  const el = document.getElementById("reg-msg");
  el.textContent = text;
  el.className = isErr ? "msg err" : "msg";
  el.hidden = false;
}

const val = id => document.getElementById(id).value.trim();

document.getElementById("reg").onsubmit = async e => {
  e.preventDefault();
  const r = await fetch("/api/sites", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name: val("f-name"), url: val("f-url"), note: val("f-note") }),
  });
  const d = await r.json();
  if (!r.ok) return msg(d.error || "登録できませんでした", true);
  ["f-name", "f-url", "f-note"].forEach(id => document.getElementById(id).value = "");
  msg(`${d.name} を登録しました。下のタグをページに貼ってください。`, false);
  showTag(d.name);
  load();
};

// 一覧は load() ごとに作り直すので、行ではなく入れ物にハンドラを付ける。
document.getElementById("sites").onclick = async e => {
  const name = e.target.dataset.tag, del = e.target.dataset.del;
  if (name) return showTag(name);
  if (!del) return;
  if (!confirm(`${del} を登録簿から外します。記録済みのログは消えません。`)) return;
  const r = await fetch("/api/sites/" + encodeURIComponent(del), { method: "DELETE" });
  const d = await r.json();
  msg(r.ok ? `${del} を外しました` : (d.error || "削除できませんでした"), !r.ok);
  load();
};

async function load() {
  const d = await (await fetch(`/api/summary?days=${days}&bots=${bots}`)).json();
  document.getElementById("kpis").innerHTML = `
    <div class="kpi"><div class="n">${num(d.total_views)}</div><div class="l">ページビュー</div></div>
    <div class="kpi"><div class="n">${num(d.total_visitors)}</div><div class="l">訪問者 (日次ユニークの延べ)</div></div>
    <div class="kpi"><div class="n">${num(d.sites.length)}</div><div class="l">サイト</div></div>
    <div class="kpi"><div class="n">${d.daily.length ? (d.total_views / d.daily.length).toFixed(1) : "0"}</div><div class="l">1日あたりPV</div></div>`;
  bars(document.getElementById("chart"), d.daily.map(r => ({ views: r.views, key: r.date })), r => r.key);
  const rg = document.getElementById("range");
  rg.innerHTML = d.daily.length ? `<span>${d.daily[0].date}</span><span>${d.daily.at(-1).date}</span>` : "";
  bars(document.getElementById("hours"), d.hours, r => r.key + "時");
  document.getElementById("sites").innerHTML = sitesTable(d.sites);
  document.getElementById("paths").innerHTML = table(d.paths, "パス");
  document.getElementById("refs").innerHTML = table(d.refs, "ホスト");
  document.getElementById("devices").innerHTML = table(d.devices, "種別");
}

document.querySelectorAll("[data-d]").forEach(b => b.onclick = () => {
  days = +b.dataset.d;
  document.querySelectorAll("[data-d]").forEach(x => x.classList.toggle("on", x === b));
  load();
});
document.getElementById("bots").onclick = e => {
  bots = bots ? 0 : 1;
  e.target.classList.toggle("on", !!bots);
  load();
};
showTag("myapp");
load();
</script></body></html>"""


if __name__ == "__main__":
    import uvicorn

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    host = os.environ.get("VISIT_LOG_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=PORT, timeout_graceful_shutdown=5, access_log=False)
