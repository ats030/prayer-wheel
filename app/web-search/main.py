"""Shared search API. Site search, YaCy and legacy SearXNG never fall back.

Provider configuration is operator-owned; callers cannot supply an endpoint.
No page body is downloaded here. Terms snapshots travel with each result.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

load_dotenv(Path.home() / ".env")
CONFIG_PATH = Path(os.environ.get("WEB_SEARCH_CONFIG", Path(__file__).with_name("sources.json")))
UA = "ats030-web-search/1.0 (https://github.com/ats030; source research)"
TIMEOUT = httpx.Timeout(12, connect=4)
_index_cache: dict[str, tuple[float, dict]] = {}
app = FastAPI(title="web-search", docs_url=None, redoc_url=None)


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or "." not in host or host.endswith((".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def in_source(url: str, source: dict) -> bool:
    if not public_url(url):
        return False
    p = urlsplit(url)
    return any(
        p.scheme == urlsplit(prefix).scheme
        and p.netloc == urlsplit(prefix).netloc
        and p.path.startswith(urlsplit(prefix).path)
        for prefix in source.get("url_prefixes", [])
    )


def enabled(source: dict) -> bool:
    terms = source.get("terms", {})
    return bool(source.get("enabled") and source.get("url_prefixes")
                and terms.get("status") in {"approved", "conditional"}
                and terms.get("checked_at") and terms.get("links") and terms.get("conditions"))


def fetch(client: httpx.Client, url: str, params=None) -> httpx.Response:
    # Explicit endpoint only. No redirect to a different host or an HTML login.
    response = client.get(url, params=params)
    response.raise_for_status()
    if response.is_redirect:
        raise ValueError("検索APIがリダイレクトしました")
    if len(response.content) > 8_000_000:
        raise ValueError("検索応答が上限を超えました")
    return response


def parse_opensearch(response: httpx.Response) -> list[dict]:
    """OpenSearch Suggestions JSON, RSS and Atom result feeds."""
    if "json" in response.headers.get("content-type", ""):
        data = response.json()
        if not isinstance(data, list) or len(data) < 4 or not all(isinstance(x, list) for x in data[1:4]):
            raise ValueError("OpenSearch JSONの形式が不正です")
        return [dict(title=str(title), url=str(url), content=str(desc))
                for title, desc, url in zip(data[1], data[2], data[3])]
    raw = response.content
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("外部実体を含むXMLは利用できません")
    root = ET.fromstring(raw)
    hits = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields = {child.tag.split("}")[-1]: child for child in node}
        link = fields.get("link")
        url = "" if link is None else link.attrib.get("href", link.text or "")
        hits.append({"url": url.strip(), "title": fields.get("title").text or ""
                     if fields.get("title") is not None else "", "content": ""})
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("OpenSearch RSS/Atomの形式が不正です")
    return hits


def sphinx_search(client: httpx.Client, source: dict, query: str, limit: int) -> list[dict]:
    endpoint = source["endpoint"]
    cached = _index_cache.get(endpoint)
    if not cached or time.monotonic() - cached[0] > 3600:
        body = fetch(client, endpoint).text.strip()
        if not body.startswith("Search.setIndex(") or not body.rstrip(";").endswith(")"):
            raise ValueError("Sphinx検索索引の形式が不正です")
        index = json.loads(body.rstrip(";")[len("Search.setIndex("):-1])
        _index_cache[endpoint] = (time.monotonic(), index)
    else:
        index = cached[1]
    # Exact title tokens, then the intersection of body-index tokens. Do not
    # pretend this is Sphinx's JavaScript stemmer or a semantic search.
    tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
    if not tokens:
        return []
    title_hits = [i for i, title in enumerate(index["titles"])
                  if tokens <= set(re.findall(r"[a-z0-9_]+", title.lower()))]
    sets = []
    for token in tokens:
        ids = index.get("terms", {}).get(token, [])
        sets.append(set(ids if isinstance(ids, list) else [ids]))
    ids = title_hits + sorted(set.intersection(*sets) - set(title_hits))
    return [{"url": source["base_url"] + index["docnames"][i] + ".html",
             "title": index["titles"][i], "content": ""} for i in ids[:limit]]


def site_search(source: dict, query: str, limit: int) -> tuple[list[dict], str]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
            kind = source["kind"]
            if kind == "sphinx":
                hits = sphinx_search(client, source, query, limit)
            else:
                endpoint = source["endpoint"].replace("{searchTerms}", quote(query, safe="")).replace("{count}", str(limit))
                response = fetch(client, endpoint)
                if kind == "opensearch":
                    hits = parse_opensearch(response)
                elif kind == "json":
                    data = response.json()
                    for key in source.get("results_path", "results").split("."):
                        data = data[key]
                    if not isinstance(data, list):
                        raise ValueError("検索結果が配列ではありません")
                    hits = [{"url": row[source.get("url_key", "url")],
                             "title": row.get(source.get("title_key", "title"), ""),
                             "content": row.get(source.get("content_key", "content"), "")}
                            for row in data]
                else:
                    raise ValueError("未対応の検索方式です")
        kept = []
        for hit in hits:
            if isinstance(hit.get("url"), str) and in_source(hit["url"], source):
                kept.append({**hit, "provider": source["id"], "terms": source["terms"],
                             "url_prefixes": source["url_prefixes"]})
        return kept[:limit], ""
    except (httpx.HTTPError, ValueError, KeyError, TypeError, ET.ParseError):
        return [], f"{source['id']}: 検索先への接続または応答の処理に失敗しました"


def general_search(kind: str, query: str, limit: int, cfg: dict) -> tuple[list[dict], list[str]]:
    endpoint = (os.environ.get("YACY_API_URL", "http://127.0.0.1:8090") if kind == "yacy"
                else os.environ.get("SEARXNG_API_URL", "")).rstrip("/")
    if not endpoint:
        return [], [f"{kind}: 接続先が未設定です"]
    params = {"query": query, "maximumRecords": limit, "resource": "global", "contentdom": "text"} if kind == "yacy" else {"q": query, "format": "json", "language": "ja"}
    endpoint = endpoint + "/yacysearch.json" if kind == "yacy" else (endpoint if endpoint.endswith("/search") else endpoint + "/search")
    try:
        with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
            payload = fetch(client, endpoint, params).json()
        if kind == "yacy":
            hits = payload["channels"][0]["items"]
            # YaCy's JSON feed carries HTML-escaped links and text. Decode
            # entities before validating or fetching URLs with query strings.
            results = [{"url": html.unescape(row["link"]),
                        "title": html.unescape(str(row.get("title", ""))),
                        "content": html.unescape(str(row.get("description", "")))} for row in hits]
        else:
            results = payload["results"]
            if not results and payload.get("unresponsive_engines"):
                return [], ["SearXNGの上流検索エンジンが応答していません"]
        if not isinstance(results, list):
            raise ValueError("結果が配列ではありません")
        # General search is a discovery route, never a blanket content licence.
        terms = cfg["general_terms"][kind]
        return [{"url": row["url"], "title": row.get("title", ""), "content": row.get("content", ""),
                 "provider": kind, "terms": terms, "url_prefixes": []}
                for row in results if isinstance(row, dict) and isinstance(row.get("url"), str)
                and public_url(row["url"])][:limit], []
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return [], [f"{kind}: 検索先への接続または応答の処理に失敗しました"]


@app.get("/sources")
def sources() -> dict:
    cfg = config()
    return {"sources": [{"id": s["id"], "kind": s["kind"], "enabled": enabled(s),
                         "url_prefixes": s["url_prefixes"], "terms": s["terms"]} for s in cfg["sources"]]}


@app.get("/health")
@app.get("/")
def health() -> dict:
    # Configuration readiness only; search failures are reported by /search.
    return {"ok": True, "site_sources": sum(enabled(s) for s in config()["sources"])}


@app.get("/search")
def search(q: str = Query(min_length=1, max_length=500),
           scope: str = Query(default="sites", pattern="^(sites|yacy|searxng)$"),
           limit: int = Query(default=6, ge=1, le=20), source: str = "") -> dict:
    if not q.strip():
        raise HTTPException(422, "検索語を入力してください")
    cfg = config()
    errors = []
    if scope == "sites":
        selected = [s for s in cfg["sources"] if enabled(s) and (not source or source == s["id"])]
        if not selected:
            raise HTTPException(503, "利用条件を確認した検索先がありません")
        with ThreadPoolExecutor(max_workers=min(4, len(selected))) as pool:
            batches = list(pool.map(lambda s: site_search(s, q, limit), selected))
        # Round robin so one source cannot fill every candidate slot.
        results = [batch[i] for i in range(limit) for batch, _ in batches if i < len(batch)]
        errors = [error for _, error in batches if error]
    else:
        if source:
            raise HTTPException(422, "sourceは指定サイト検索だけで使用できます")
        results, errors = general_search(scope, q, limit, cfg)
    unique = {row["url"]: row for row in reversed(results)}
    hits = list(reversed(list(unique.values())))[:limit]
    # Fail closed on partial provider failures; consumers must not treat a
    # truncated search as a complete successful collection.
    return {"scope": scope, "results": hits, "errors": errors,
            "ok": bool(hits) and not errors,
            "searched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}


UI_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenSearch 検索</title>
<script src="http://ubuntu-server-app:8526/v.js" data-site="web-search" defer></script>
<style>
:root {{ --bg: #fafaf9; --fg: #1c1917; --muted: #78716c; --line: #e7e5e4; --link: #1d4ed8; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #1c1917; --fg: #f5f5f4; --muted: #a8a29e; --line: #44403c; --link: #93c5fd; }}
}}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.6 system-ui, sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 24px 16px; }}
form {{ display: flex; gap: 8px; flex-wrap: wrap; }}
input, select, button {{ font: inherit; padding: 6px 10px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--bg); color: var(--fg); }}
input {{ flex: 1 1 240px; min-width: 0; }}
a {{ color: var(--link); }}
li {{ margin: 14px 0; overflow-wrap: anywhere; }}
.meta, .note {{ color: var(--muted); font-size: 13px; }}
.error {{ color: #b91c1c; }}
</style></head><body><main>
<h1>OpenSearch 検索</h1>
<form method="get" action="/ui">
<input name="q" value="{q}" placeholder="検索語" required autofocus>
<select name="source">{options}</select>
<button>検索</button>
</form>
<p class="note">登録済みの検索先だけを検索します。再利用時は各結果の利用条件に従ってください。
<a href="/sources">検索先一覧 (JSON)</a></p>
{body}
</main></body></html>"""


def _plain(text: str) -> str:
    # Sphinx titles carry markup; show them as text.
    return html.escape(html.unescape(re.sub(r"<[^>]+>", "", text or "")))


@app.get("/ui", response_class=HTMLResponse)
def ui(q: str = Query(default="", max_length=500), source: str = "") -> str:
    ids = [s["id"] for s in config()["sources"] if enabled(s)]
    options = "".join(f'<option value="{html.escape(i)}"{" selected" if i == source else ""}>{html.escape(i)}</option>'
                      for i in [""] + ids).replace('<option value="">', '<option value="">すべて', 1)
    body = ""
    if q.strip():
        try:
            data = search(q, "sites", 10, source if source in ids else "")
        except HTTPException as exc:
            data = {"results": [], "errors": [str(exc.detail)]}
        items = "".join(
            f'<li><a href="{html.escape(r["url"])}" rel="noreferrer">{_plain(r.get("title")) or html.escape(r["url"])}</a>'
            f'<div class="meta">{html.escape(r.get("provider", ""))} · {html.escape(r["terms"].get("license", ""))}</div>'
            + (f'<div>{_plain(r["content"])}</div>' if r.get("content") else "") + "</li>"
            for r in data["results"])
        errors = "".join(f'<p class="error">{html.escape(e)}</p>' for e in data["errors"])
        body = errors + (f"<ol>{items}</ol>" if items else "<p>該当なし</p>")
    return UI_PAGE.format(q=html.escape(q), options=options, body=body)
