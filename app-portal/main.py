"""app-portal: 生成したアプリの一覧ポータル (port 8500)

~/.config/systemd/user/*.service を自動スキャンし、
Description の「(port 85xx)」表記からWebアプリを検出してリンク集を生成する。
ポート表記のないサービスは「バックグラウンド」として稼働状態のみ表示する。
"""

import re
import socket
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
SELF_UNIT = "app-portal.service"
PORT_RE = re.compile(r"port\s*(\d{4,5})", re.IGNORECASE)

app = FastAPI(title="App Portal")
APP_EMOJI = {
    "kangaeru-mame.service": "🫛",
    "gathering-information.service": "🔎",
    "image-editor.service": "🪄",
    "image-generator.service": "🎨",
    "markdown-generator.service": "📝",
    "memo.service": "🗒️",
    "patent-miner.service": "💡",
    "rekimeshi-web.service": "🍚",
    "rss-reader.service": "📰",
    "web-clipper.service": "✂️",
    "writing.service": "✍️",
    "x-analyzer.service": "📊",
    "x-post.service": "🐦",
}
DEFAULT_APP_EMOJI = "🧩"


def discover_units() -> list[dict]:
    units = []
    for f in sorted(UNIT_DIR.glob("*.service")):
        if f.name == SELF_UNIT:
            continue
        desc = ""
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.startswith("Description="):
                    desc = line.split("=", 1)[1].strip()
                    break
        except OSError:
            continue
        m = PORT_RE.search(desc)
        port = int(m.group(1)) if m else None
        name = re.sub(r"\s*\(port\s*\d+\)", "", desc, flags=re.IGNORECASE)
        name = re.sub(r",?\s*port\s*\d+", "", name, flags=re.IGNORECASE)
        name = name.strip() or f.stem
        units.append({"unit": f.name, "name": name, "port": port})
    return units


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def derive_status(service_state: str, port: int | None) -> str:
    """up / down / starting / error の4状態に集約する。"""
    if service_state == "active":
        if port is not None and not port_open(port):
            return "error"
        return "up"
    if service_state == "activating":
        return "starting"
    if service_state in ("inactive", "deactivating"):
        return "down"
    return "error"  # failed など


def collect_status() -> list[dict]:
    units = discover_units()
    if not units:
        return []
    result = subprocess.run(
        ["systemctl", "--user", "is-active", *(u["unit"] for u in units)],
        capture_output=True,
        text=True,
    )
    states = result.stdout.splitlines()
    for unit, state in zip(units, states):
        unit["service_state"] = state
        unit["status"] = derive_status(state, unit["port"])
    return units



def _emoji_icon(emoji: str) -> tuple[bytes, str]:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#eef0ff"/>
<text x="32" y="45" text-anchor="middle" font-family="Apple Color Emoji,Segoe UI Emoji,Noto Color Emoji,sans-serif" font-size="39">{emoji}</text>
</svg>"""
    return svg.encode(), "image/svg+xml"


@app.get("/api/status")
def api_status() -> JSONResponse:
    return JSONResponse({"services": collect_status()})



@app.get("/favicon.svg")
def favicon() -> Response:
    data, media_type = _emoji_icon("🏠")
    return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/favicon/{port}")
def api_favicon(port: int) -> Response:
    unit = next((item for item in discover_units() if item["port"] == port), None)
    if unit is None:
        return Response(status_code=404)
    emoji = APP_EMOJI.get(unit["unit"], DEFAULT_APP_EMOJI)
    data, media_type = _emoji_icon(emoji)
    return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})


PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>App Portal</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
  :root {
    --bg: #f5f6f8; --card: #ffffff; --text: #1c2024; --muted: #6c7278;
    --border: #e0e3e7; --up: #2fbf71; --down: #9aa0a6; --error: #e5484d;
    --starting: #f5a623; --link: #1c2024;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181c; --card: #1f2328; --text: #e8eaed; --muted: #9aa0a6;
      --border: #33383f; --link: #e8eaed;
    }
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, "Hiragino Sans", "Noto Sans CJK JP", sans-serif;
    padding: 2rem 1.5rem; max-width: 1080px; margin: 0 auto;
  }
  h1 { font-size: 1.4rem; margin-bottom: 1.5rem; }
  h2 { font-size: 0.9rem; color: var(--muted); margin: 2rem 0 0.8rem;
       text-transform: uppercase; letter-spacing: 0.05em; }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 0.8rem;
  }
  a.card {
    display: block; background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 0.9rem 1rem; text-decoration: none;
    color: var(--link); transition: border-color 0.15s, transform 0.15s;
  }
  a.card:hover { border-color: var(--muted); transform: translateY(-1px); }
  a.card.dead { opacity: 0.55; pointer-events: none; }
  .card-head { display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.55rem; }
  .favicon { width: 30px; height: 30px; border-radius: 7px; flex-shrink: 0; object-fit: contain; }
  .card .name { font-weight: 600; line-height: 1.35; }
  .meta { display: flex; align-items: center; gap: 0.4rem;
          font-size: 0.78rem; color: var(--muted); }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot.up { background: var(--up); }
  .dot.down { background: var(--down); }
  .dot.error { background: var(--error); }
  .dot.starting { background: var(--starting); }
  ul.bg { list-style: none; display: flex; flex-wrap: wrap; gap: 0.5rem 1.4rem; }
  ul.bg li { display: flex; align-items: center; gap: 0.45rem;
             font-size: 0.85rem; color: var(--muted); }
  footer { margin-top: 2.5rem; font-size: 0.75rem; color: var(--muted); }
</style>
</head>
<body>
  <h1>🏠 App Portal</h1>
  <div id="apps" class="grid"></div>
  <h2>バックグラウンド</h2>
  <ul id="background" class="bg"></ul>
  <footer id="updated"></footer>
<script>
const LABELS = { up: "稼働", down: "停止", starting: "起動中", error: "異常" };

function esc(s) {
  return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function render(services) {
  const apps = services.filter(s => s.port !== null);
  const bg = services.filter(s => s.port === null);

  document.getElementById("apps").innerHTML = apps.map(s => {
    const url = `http://${location.hostname}:${s.port}/`;
    const dead = s.status !== "up" ? " dead" : "";
    return `<a class="card${dead}" href="${url}" target="_blank" rel="noopener">
      <div class="card-head"><img class="favicon" src="/api/favicon/${s.port}?v=emoji-1" alt=""><div class="name">${esc(s.name)}</div></div>
      <div class="meta"><span class="dot ${s.status}"></span>${LABELS[s.status]} · :${s.port}</div>
    </a>`;
  }).join("");

  document.getElementById("background").innerHTML = bg.map(s =>
    `<li><span class="dot ${s.status}"></span>${esc(s.name)}</li>`
  ).join("");

  document.getElementById("updated").textContent =
    "最終更新: " + new Date().toLocaleTimeString("ja-JP");
}

async function refresh() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    render(data.services);
  } catch (e) { /* 次回ポーリングで回復 */ }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8500)
