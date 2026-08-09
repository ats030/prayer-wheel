"""Minimal Amazon Creators API client for one related book."""
from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx

TOKEN_URL = "https://api.amazon.co.jp/auth/o2/token"
SEARCH_URL = "https://creatorsapi.amazon/catalog/v1/searchItems"
MARKETPLACE = "www.amazon.co.jp"
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}

class CreatorsAPIError(RuntimeError):
    pass

def _token(credential_id: str, secret: str) -> str:
    now = time.monotonic()
    cached = _TOKEN_CACHE.get(credential_id)
    if cached and cached[1] > now + 60:
        return cached[0]
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(credential_id)
        if cached and cached[1] > time.monotonic() + 60:
            return cached[0]
        try:
            response = httpx.post(TOKEN_URL, json={"grant_type": "client_credentials", "client_id": credential_id, "client_secret": secret, "scope": "creatorsapi::default"}, timeout=15)
            response.raise_for_status()
            data = response.json()
            token = str(data.get("access_token") or "")
            expires = max(60, int(data.get("expires_in") or 3600))
            if not token:
                raise ValueError("missing token")
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise CreatorsAPIError("Amazon商品APIを認証できませんでした") from exc
        _TOKEN_CACHE[credential_id] = (token, time.monotonic() + expires)
        return token

def _value(container: Any, *keys: str) -> str:
    current = container
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if isinstance(current, dict):
        current = current.get("displayValue") or current.get("value")
    return str(current or "").strip()

def search_book(query: str, credential_id: str, secret: str, partner_tag: str) -> dict[str, str] | None:
    term = " ".join(str(query).split())[:80]
    if not term:
        return None
    token = _token(credential_id, secret)
    try:
        response = httpx.post(SEARCH_URL, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "x-marketplace": MARKETPLACE}, json={"marketplace": MARKETPLACE, "partnerTag": partner_tag, "searchIndex": "Books", "keywords": f"{term} 図鑑", "itemCount": 1, "resources": ["itemInfo.title", "images.primary.medium"]}, timeout=20)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise CreatorsAPIError("Amazonの商品情報を取得できませんでした") from exc
    result = data.get("searchResult") or data.get("SearchResult") or {}
    items = result.get("items") or result.get("Items") or []
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    url = _value(item, "detailPageURL") or _value(item, "DetailPageURL")
    title = _value(item, "itemInfo", "title") or _value(item, "ItemInfo", "Title")
    image = _value(item, "images", "primary", "medium", "url") or _value(item, "Images", "Primary", "Medium", "URL")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not (parsed.hostname == "amazon.co.jp" or parsed.hostname.endswith(".amazon.co.jp")) or not title:
        return None
    return {"title": title[:240], "url": url, "image": image}
