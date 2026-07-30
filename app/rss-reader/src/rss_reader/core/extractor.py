import diskcache
import trafilatura
from bs4 import BeautifulSoup

from ..config import ARTICLE_CACHE_TTL, CACHE_DIR
from .fetcher import fetch_bytes

_cache = diskcache.Cache(str(CACHE_DIR))


def extract_article(url: str) -> str:
    cached = _cache.get(url)
    if cached is not None:
        return cached

    text = _fetch_and_extract(url)
    _cache.set(url, text, expire=ARTICLE_CACHE_TTL)
    return text


def _fetch_and_extract(url: str) -> str:
    try:
        raw, _ = fetch_bytes(url)
        html = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"記事の取得に失敗しました: {e}"

    text = trafilatura.extract(html, include_comments=False, include_tables=True)
    if text and len(text) >= 200:
        return text

    try:
        from readability import Document
        doc = Document(html)
        text = BeautifulSoup(doc.summary(), "lxml").get_text(separator="\n", strip=True)
        if text and len(text) >= 200:
            return text
    except Exception:
        pass

    text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)
    return text or "本文を抽出できませんでした。"
