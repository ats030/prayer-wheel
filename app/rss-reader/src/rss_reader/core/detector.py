import json
import re
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from ..config import FEED_KEYWORDS_IN_HREF, HEURISTIC_PATHS
from .fetcher import fetch_bytes


def _resolve_apple_podcasts(url: str) -> list[str]:
    id_match = re.search(r"/id(\d+)", url)
    if not id_match:
        return []
    podcast_id = id_match.group(1)

    # 1. iTunes Lookup API (ID直引き)
    try:
        raw, _ = fetch_bytes(
            f"https://itunes.apple.com/lookup?id={podcast_id}&entity=podcast"
        )
        data = json.loads(raw)
        feed_url = (data.get("results") or [{}])[0].get("feedUrl")
        if feed_url:
            return [feed_url]
    except Exception:
        pass

    # 2. iTunes Search API (URL パスのポッドキャスト名で検索)
    name_match = re.search(r"/podcast/([^/]+)/", url)
    if name_match:
        term = name_match.group(1).replace("-", " ")
        country_match = re.search(r"podcasts\.apple\.com/([a-z]{2})/", url)
        country = country_match.group(1) if country_match else "us"
        try:
            raw, _ = fetch_bytes(
                f"https://itunes.apple.com/search?term={term}&entity=podcast"
                f"&country={country}&limit=5"
            )
            data = json.loads(raw)
            for result in data.get("results", []):
                if str(result.get("collectionId")) == podcast_id:
                    feed_url = result.get("feedUrl")
                    if feed_url:
                        return [feed_url]
            # ID一致なければ最上位を返す
            feed_url = (data.get("results") or [{}])[0].get("feedUrl")
            if feed_url:
                return [feed_url]
        except Exception:
            pass

    return []


def _is_feed_content_type(ct: str) -> bool:
    ct = ct.lower()
    return any(k in ct for k in ("xml", "rss", "atom"))


def _probe_url(url: str) -> bool:
    try:
        raw, ct = fetch_bytes(url)
        if _is_feed_content_type(ct):
            return True
        parsed = feedparser.parse(raw)
        return bool(parsed.entries)
    except Exception:
        return False


def detect_and_resolve(url: str) -> list[str]:
    if "podcasts.apple.com" in url:
        result = _resolve_apple_podcasts(url)
        if result:
            return result

    auth_blocked = False
    try:
        raw, ct = fetch_bytes(url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            auth_blocked = True
        else:
            raise ValueError(f"URLの取得に失敗しました: {e}") from e
    except Exception as e:
        raise ValueError(f"URLの取得に失敗しました: {e}") from e

    if not auth_blocked:
        if _is_feed_content_type(ct):
            return [url]

        parsed = feedparser.parse(raw)
        if parsed.entries:
            return [url]

        soup = BeautifulSoup(raw, "lxml")
        found = []

        # <link rel="alternate"> — type 属性で判定
        for tag in soup.find_all("link", rel="alternate"):
            t = tag.get("type", "")
            href = tag.get("href", "")
            if href and ("rss" in t or "atom" in t or "feed" in t):
                found.append(urljoin(url, href))

        # <link rel="alternate"> — href に feed キーワードを含む（type 省略サイト対策）
        for tag in soup.find_all("link", rel="alternate"):
            href = tag.get("href", "")
            if href and any(k in href.lower() for k in FEED_KEYWORDS_IN_HREF):
                candidate = urljoin(url, href)
                if candidate not in found:
                    found.append(candidate)

        # <a href> — href や テキストに feed キーワードを含むリンク
        for tag in soup.find_all("a", href=True):
            href = tag["href"]
            text = tag.get_text(strip=True).lower()
            if any(k in href.lower() for k in FEED_KEYWORDS_IN_HREF) or \
               any(k in text for k in ("rss", "feed", "atom", "フィード", "購読")):
                candidate = urljoin(url, href)
                parsed_c = urlparse(candidate)
                if parsed_c.scheme in ("http", "https") and candidate not in found:
                    found.append(candidate)

        # 候補を実際に検証して有効なフィードだけ残す
        verified = [c for c in found if _probe_url(c)]
        if verified:
            return verified

    # ヒューリスティックパス探索（401/403 blocked の場合はここから開始）
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

    # 入力URLがルート以外で blocked → ルートページの autodiscovery を試みる
    if auth_blocked and url.rstrip("/") != base:
        try:
            root_raw, _ = fetch_bytes(base + "/")
            soup = BeautifulSoup(root_raw, "lxml")
            root_found = []
            for tag in soup.find_all("link", rel="alternate"):
                t = tag.get("type", "")
                href = tag.get("href", "")
                if href and ("rss" in t or "atom" in t or "feed" in t):
                    root_found.append(urljoin(base, href))
            for tag in soup.find_all("link", rel="alternate"):
                href = tag.get("href", "")
                if href and any(k in href.lower() for k in FEED_KEYWORDS_IN_HREF):
                    candidate = urljoin(base, href)
                    if candidate not in root_found:
                        root_found.append(candidate)
            root_verified = [c for c in root_found if _probe_url(c)]
            if root_verified:
                return root_verified
        except Exception:
            pass

    heuristic_found = [
        base + path for path in HEURISTIC_PATHS if _probe_url(base + path)
    ]

    if not heuristic_found and auth_blocked:
        raise ValueError(
            "このサイトへのアクセスが制限されています（401）。"
            "RSSフィードのURLを直接入力してください。"
        )

    return heuristic_found
