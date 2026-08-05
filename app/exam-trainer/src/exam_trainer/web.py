"""Material collection: SearXNG search + trafilatura extraction.

Adapted from writing/web.py. The difference is what happens to the text: writing
feeds it to a model as background reading, while here every collected passage is
kept verbatim in the database, because a question is only allowed to exist if it
points back at the passage it came from.
"""

from __future__ import annotations

import logging
import time
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


@dataclass
class Material:
    url: str
    title: str
    text: str


def available() -> bool:
    """Is search configured? Says nothing about whether it answers."""
    return bool(settings.searxng_url)


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
    if not settings.searxng_url:
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


def search_urls(query: str, limit: int = 6) -> list[dict]:
    if not settings.searxng_url:
        logger.info("SEARXNG_API_URL not set; skipping search")
        return []
    params = {"q": query, "format": "json", "language": "ja"}
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            resp = client.get(_search_endpoint(), params=params)
            resp.raise_for_status()
        results = resp.json().get("results", [])
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("SearXNG search failed: %s", exc)
        return []
    return [hit for hit in results if not _blocked(hit.get("url", ""))][:limit]


def _blocked(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in BLOCKED_HOST_HINTS)


def extract_url(url: str) -> Material | None:
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
        html = resp.text
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
    return Material(url=url, title=title, text=text)


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
        material = extract_url(url)
        if material:
            material.text = material.text[:max_chars]
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
