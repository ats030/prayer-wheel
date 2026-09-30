"""Material collection: SearXNG search + trafilatura extraction.

Adapted from writing/web.py. The difference is what happens to the text: writing
feeds it to a model as background reading, while here every collected passage is
kept verbatim in the database, because a question is only allowed to exist if it
points back at the passage it came from.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import ipaddress
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
import trafilatura

from .config import settings

logger = logging.getLogger(__name__)

# trafilatura.fetch_url() retries with a 30s read timeout, so one slow site can
# stall a whole collection run; fetch with httpx under a tight bound instead.
_FETCH_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
_GATHER_BUDGET_SEC = 40.0
_UA = "Mozilla/5.0 (compatible; exam-trainer/1.0)"

# Sites that host exam questions rather than explanations. Pulling from these
# risks reproducing copyrighted items; the app writes its own questions from
# primary sources instead.
BLOCKED_HOST_HINTS = ("kakomon", "過去問", "mondai-shu")

# Pages that cannot carry an explanation whatever the query. Kept separate from
# BLOCKED_HOST_HINTS because the reason differs: that list is about copyright,
# this one about there being no body to extract. Measured across three exams
# with six candidates per node, these filled roughly half the slots and yielded
# 0-185 characters each; one node's entire candidate list was junk and its only
# material ended up being the 185 characters on Yahoo's front page.
#
# The wasted fetch is the smaller cost. Material order decides what gets asked
# (generate.py stops at the target), so a video page at the top of the list
# starves the node it was collected for.
UNUSABLE_URL_HINTS = (
    # Video, social, shopping, courseware: no article body.
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com",
    "twitter.com", "pinterest.", "amazon.co", "rakuten.co", "udemy.com",
    # Flashcards reproduce exam items — the BLOCKED_HOST_HINTS reason applies
    # here too, but the hostname carries no hint of it.
    "quizlet.com",
    # Search engines' own pages. Meta-search backends hand back front pages and
    # result listings as if they were results.
    "/search?", "/results?", "search_query=",
    "www.google.com/", "www.yahoo.co.jp/", "search.yahoo.", "www.bing.com/",
    "duckduckgo.com/", "startpage.com/", "ecosia.org/", "zapmeta.",
)

# Enough text for at least one passage (web.passages splits at 1200) plus the
# overlap. Below this a page may extract cleanly and still not support a single
# question.
MIN_MATERIAL_CHARS = 800


@dataclass
class Material:
    url: str
    title: str
    text: str
    provenance: dict | None = None


_scope: ContextVar[str | None] = ContextVar("search_scope", default=None)
_note: ContextVar[str] = ContextVar("search_note", default="")


def current_scope() -> str:
    return _scope.get() or (settings.search_default_scope if settings.web_search_url else "searxng")


@contextmanager
def search_mode(scope: str):
    if scope not in {"sites", "yacy", "searxng"}:
        raise ValueError("未知の検索範囲です")
    token = _scope.set(scope)
    note_token = _note.set("")
    try:
        yield
    finally:
        _scope.reset(token)
        _note.reset(note_token)


def scope_options() -> list[dict]:
    if settings.web_search_url:
        return [{"id": "sites", "label": "指定サイト（公式資料）"},
                {"id": "yacy", "label": "Web全般（YaCy）"},
                {"id": "searxng", "label": "Web全般（SearXNG・移行用）"}]
    return [{"id": "searxng", "label": "Web全般（SearXNG）"}]


def reviewed_sources() -> list[dict]:
    """Revalidate cached pages against today's operator registry."""
    with httpx.Client(timeout=5) as client:
        response = client.get(settings.web_search_url.rstrip("/") + "/sources")
        response.raise_for_status()
        sources = response.json()["sources"]
    if not isinstance(sources, list):
        raise ValueError("検索先の設定を確認できません")
    return [source for source in sources if source.get("enabled")]


def matches_source(url: str, source: dict) -> bool:
    p = urllib.parse.urlsplit(url)
    return any(p.scheme == urllib.parse.urlsplit(prefix).scheme
               and p.netloc == urllib.parse.urlsplit(prefix).netloc
               and p.path.startswith(urllib.parse.urlsplit(prefix).path)
               for prefix in source.get("url_prefixes", []))


def available() -> bool:
    """Is search configured? Says nothing about whether it answers."""
    return bool(settings.web_search_url or (current_scope() == "searxng" and settings.searxng_url))


# Reachability is cached briefly: /health and the generate endpoint both ask,
# and a dead host costs a full connect timeout each time.
_REACHABLE_TTL_SEC = 30.0
_reachable_cache: tuple[float, bool] | None = None


def reachable(force: bool = False) -> bool:
    """Does the configured SearXNG actually answer?

    `available()` alone was what let a stale SEARXNG_API_URL sit unnoticed: the
    UI offered web search because the setting was non-empty, while every search
    silently returned nothing (the host had moved and search_urls swallows the
    connection error). Anything that tells the user "web search works" must ask
    this instead.
    """
    global _reachable_cache
    if settings.web_search_url:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(settings.web_search_url.rstrip("/") + "/health")
                resp.raise_for_status()
                return resp.json().get("ok") is True
        except (httpx.HTTPError, ValueError):
            return False
    if not available():
        return False
    now = time.monotonic()
    if not force and _reachable_cache and now - _reachable_cache[0] < _REACHABLE_TTL_SEC:
        return _reachable_cache[1]
    try:
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0), follow_redirects=True) as client:
            resp = client.get(_search_endpoint(), params={"q": "ping", "format": "json"})
            resp.raise_for_status()
            ok = isinstance(resp.json().get("results"), list)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("SearXNG unreachable at %s: %s", settings.searxng_url, exc)
        ok = False
    _reachable_cache = (now, ok)
    return ok


def _search_endpoint() -> str:
    base = settings.searxng_url.rstrip("/")
    return base if base.endswith("/search") else base + "/search"


# Set when SearXNG answered but its upstream engines were all refusing. Read by
# the generation job so "no material" can name its cause.
_last_search_note = ""


def last_search_note() -> str:
    return _note.get() if settings.web_search_url else _last_search_note


def search_urls(query: str, limit: int = 6) -> list[dict]:
    global _last_search_note
    _last_search_note = ""
    _note.set("")
    if settings.web_search_url:
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(settings.web_search_url.rstrip("/") + "/search",
                                  params={"q": query, "scope": current_scope(), "limit": min(20, limit)})
                resp.raise_for_status()
                payload = resp.json()
            if not payload.get("ok") or payload.get("errors"):
                _note.set(" / ".join(payload.get("errors") or [
                    "選択した検索範囲で資料が見つかりません。検索語を変えるか検索範囲を選び直してください"
                ]))
                return []
            results = payload["results"]
            if not isinstance(results, list):
                raise ValueError("results must be a list")
            return [hit for hit in results if isinstance(hit, dict)
                    and isinstance(hit.get("url"), str)
                    and not _blocked(hit["url"]) and not _unusable(hit["url"])][:limit]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            _note.set("選択した検索先に接続できません。検索範囲を選び直すか時間をおいて再実行してください")
            return []
    if not settings.searxng_url:
        logger.info("SEARXNG_API_URL not set; skipping search")
        return []
    params = {"q": query, "format": "json", "language": "ja"}
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            resp = client.get(_search_endpoint(), params=params)
            resp.raise_for_status()
        payload = resp.json()
        results = payload.get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("SearXNG search failed: %s", exc)
        return []

    # SearXNG answers 200 with an empty result list when every upstream engine
    # has throttled it, which looks identical to "this topic has no pages".
    # Generating for many exams in a row triggers this, so the distinction
    # matters: one means give up on the topic, the other means wait.
    if not results:
        suspended = _suspended_engines(payload)
        if suspended:
            _last_search_note = (
                "検索エンジン側が一時的に応答を拒否しています（"
                + "、".join(suspended[:3])
                + "）。時間をおいて再実行してください"
            )
            logger.warning("SearXNG upstreams suspended: %s", suspended)
    keep = [
        hit
        for hit in results
        if not _blocked(hit.get("url", "")) and not _unusable(hit.get("url", ""))
    ]
    return keep[:limit]


def _suspended_engines(payload: dict) -> list[str]:
    out = []
    for entry in payload.get("unresponsive_engines") or []:
        if isinstance(entry, (list, tuple)) and entry:
            name = str(entry[0])
            reason = str(entry[1]) if len(entry) > 1 else ""
            out.append(f"{name}: {reason}" if reason else name)
        elif entry:
            out.append(str(entry))
    return out


def _blocked(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in BLOCKED_HOST_HINTS)


def _unusable(url: str) -> bool:
    lowered = url.lower()
    if any(hint in lowered for hint in UNUSABLE_URL_HINTS):
        return True
    split = urllib.parse.urlsplit(lowered)
    # A bare front page is never an article about one syllabus item. Meta-search
    # backends hand these back as results — a ministry's home page arrived as
    # material for 自由民権運動 — and they extract to a menu of headlines that
    # reads like prose to the generator.
    if split.path in ("", "/") and not split.query:
        return True
    # trafilatura works on HTML, so a PDF costs a full download and returns
    # nothing. Judged on the path so a query string cannot hide the extension.
    return split.path.endswith(".pdf")


def _safe_result_url(url: str, prefixes: list[str] | None) -> bool:
    """Keep fetched redirects within site scope and reject private targets."""
    try:
        p = urllib.parse.urlsplit(url)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            return False
        if prefixes and not any(p.scheme == urllib.parse.urlsplit(prefix).scheme
                                and p.netloc == urllib.parse.urlsplit(prefix).netloc
                                and p.path.startswith(urllib.parse.urlsplit(prefix).path) for prefix in prefixes):
            return False
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    except (ValueError, OSError):
        return False


def extract_url(url: str, *, prefixes: list[str] | None = None, checked: bool = False) -> Material | None:
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT, follow_redirects=not checked, headers={"User-Agent": _UA}
        ) as client:
            target = url
            for _ in range(6):
                if checked and not _safe_result_url(target, prefixes):
                    return None
                resp = client.get(target)
                if not checked or not resp.is_redirect:
                    break
                target = urllib.parse.urljoin(target, resp.headers.get("location", ""))
            else:
                return None
            resp.raise_for_status()
        # Bytes, not resp.text: pages that omit charset from Content-Type make
        # httpx guess utf-8, and a Shift_JIS page then decodes to mojibake that
        # still looks like 6000 usable characters. trafilatura detects the
        # encoding itself when handed the raw bytes.
        html = resp.content
        fetched_url = str(resp.url) if getattr(resp, "url", None) else target
    except httpx.HTTPError as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        return None
    try:
        text = trafilatura.extract(html, include_comments=False) or ""
        meta = trafilatura.extract_metadata(html)
        title = meta.title if meta and meta.title else url
    except Exception as exc:  # trafilatura raises a variety of errors
        logger.warning("Extraction failed for %s: %s", url, exc)
        return None
    text = text.strip()
    if not text:
        return None
    if looks_garbled(text):
        logger.warning("Discarding garbled extraction from %s", url)
        return None
    return Material(url=fetched_url, title=title, text=text)


# Replacement chars and the CJK-compatibility block are what a mis-decoded
# Japanese page leaves behind.
_GARBLE_CHARS = "�" + "".join(chr(c) for c in range(0xF900, 0xF910))


def looks_garbled(text: str, sample: int = 400) -> bool:
    """Second line of defence for text that decoded wrong anyway.

    A page can still come back broken (mislabelled charset, a proxy that
    re-encodes). Garbled material is worse than no material here: the evidence
    check would happily confirm that a garbled quote appears in a garbled
    passage, and the question ships unreadable.
    """
    head = text[:sample]
    if not head:
        return True
    bad = sum(head.count(char) for char in _GARBLE_CHARS)
    return bad / len(head) > 0.02


def gather(query: str, limit: int = 4, max_chars: int = 6000) -> list[Material]:
    """Search, then extract the top hits within an overall time budget."""
    materials: list[Material] = []
    deadline = time.monotonic() + _GATHER_BUDGET_SEC
    for hit in search_urls(query, limit=limit * 2):
        if len(materials) >= limit:
            break
        if time.monotonic() >= deadline:
            logger.info("gather budget reached with %d materials", len(materials))
            break
        url = hit.get("url")
        if not url:
            continue
        if settings.web_search_url:
            prefixes = hit.get("url_prefixes") or []
            if current_scope() == "sites" and not prefixes:
                continue
            material = extract_url(url, prefixes=prefixes, checked=True)
        else:
            material = extract_url(url)
        if material is None:
            continue
        # A page can extract cleanly and still be a stub — a video description,
        # a product blurb. Only search results are held to this: a URL the user
        # named is their explicit choice, however short.
        if len(material.text) < MIN_MATERIAL_CHARS:
            logger.info("Skipping %s: only %d characters", url, len(material.text))
            continue
        material.text = material.text[:max_chars]
        material.provenance = {"scope": current_scope(), "provider": hit.get("provider", "searxng"),
                               "terms": hit.get("terms", {}), "url_prefixes": hit.get("url_prefixes", [])}
        materials.append(material)
    return materials


def passages(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    """Split a document into passages a question can be grounded in.

    Paragraph boundaries are preferred: a question generated from a passage that
    stops mid-sentence tends to ask about the truncated half. The overlap keeps
    a definition that straddles a boundary intact in at least one passage.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            window = text[start:end]
            for boundary in ("\n\n", "。\n", "。"):
                cut = window.rfind(boundary)
                # Only honour a boundary in the back half; an early one would
                # produce a passage too small to carry a question.
                if cut > size // 2:
                    end = start + cut + len(boundary)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks
