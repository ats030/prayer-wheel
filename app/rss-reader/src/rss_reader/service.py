"""UI-independent read/refresh logic shared by the page and fragment routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from .config import REFRESH_WORKERS
from .core import feed_cache, feed_status
from .core.fetcher import fetch_bytes, fetch_favicon
from .core.models import FeedItem, FeedMeta
from .core.parser import parse_feed, parse_feed_meta
from .core.persistence import FeedStore

SORT_ORDERS = ("重要度順", "新しい順", "古い順")
PERIODS = ("7日", "30日", "すべて")

feed_store = FeedStore()


# --- 取得 ---------------------------------------------------------------

def refresh_feed(url: str) -> tuple[FeedMeta, list[FeedItem], datetime]:
    # 成否の記録はここに置く。単発更新・追加・全更新のどの経路からでも通るため。
    try:
        raw, _ = fetch_bytes(url)
        meta = parse_feed_meta(url, raw)
        items = parse_feed(url, raw)
    except Exception as exc:
        feed_status.record_failure(url, exc)
        raise
    fetched_at = feed_cache.save(url, meta, items)
    feed_status.record_success(url)
    return meta, items, fetched_at


def load_feed(url: str) -> tuple[FeedMeta, list[FeedItem], datetime]:
    """Serve from the on-disk cache; fetch only when nothing is cached yet."""
    cached = feed_cache.load(url)
    if cached:
        return cached
    return refresh_feed(url)


def refresh_all(urls: list[str], job=None) -> list[str]:
    """Refresh every feed in parallel. Returns the URLs that failed."""
    errors: list[str] = []

    def _one(url: str) -> None:
        try:
            refresh_feed(url)
        except Exception as exc:  # noqa: BLE001 — 1件の失敗で全体を止めない
            errors.append(f"{url}: {exc}")
        finally:
            if job is not None:
                job.done += 1

    if job is not None:
        job.total = len(urls)
    workers = max(1, min(REFRESH_WORKERS, len(urls) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_one, urls))

    if job is not None:
        job.errors = errors
    return errors


# --- 集約 ---------------------------------------------------------------

def feed_title(url: str) -> str:
    cached = feed_cache.load_meta(url)
    if cached:
        return cached[0].title or url
    return url


def feed_titles(urls: list[str]) -> dict[str, str]:
    return {url: feed_title(url) for url in urls}


def thumbnail(stored_url: str, site_url: str, feed_url: str) -> str:
    """フィードが画像を持たない場合は Google favicon サービスにフォールバックする。"""
    if stored_url:
        return stored_url
    return fetch_favicon(site_url or feed_url)


def cached_items(urls: list[str]) -> tuple[list[FeedItem], datetime | None, int]:
    """Collect every cached item. Returns (items, oldest fetch time, uncached count)."""
    items: list[FeedItem] = []
    oldest: datetime | None = None
    uncached = 0
    for url in urls:
        cached = feed_cache.load(url)
        if cached is None:
            uncached += 1
            continue
        _, feed_items, fetched_at = cached
        items.extend(feed_items)
        if oldest is None or fetched_at < oldest:
            oldest = fetched_at
    return items, oldest, uncached


def failing_feeds(urls: list[str]) -> dict[str, dict]:
    """登録中のフィードのうち取得に失敗しているもの。UI の警告表示に使う。

    ``failing_since`` は経過日数（``days``）に均しておく。テンプレート側で
    日時計算をさせないため。
    """
    status = feed_status.load()
    out: dict[str, dict] = {}
    for url in urls:
        entry = status.get(url)
        if entry is None:
            continue
        since = _parse_iso(entry.get("failing_since"))
        out[url] = {
            **entry,
            "days": (datetime.now(timezone.utc) - since).days if since else None,
            "title": feed_title(url),
        }
    return out


def _parse_iso(value: str | None) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None


# --- 絞り込み・並び替え --------------------------------------------------

def _aware(dt: datetime | None) -> datetime | None:
    """フィードによっては naive な日時が混ざるため、比較前に UTC を補う。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def filter_items(
    items: list[FeedItem],
    *,
    query: str = "",
    period: str = "すべて",
    feeds: list[str] | None = None,
    genres: list[str] | None = None,
) -> list[FeedItem]:
    result = items

    if genres:
        allowed = set(genres)
        result = [i for i in result if i.media_type in allowed]

    if feeds:
        allowed = set(feeds)
        result = [i for i in result if i.feed_title in allowed]

    if period in ("7日", "30日"):
        cutoff = datetime.now(timezone.utc) - timedelta(days=7 if period == "7日" else 30)
        # 日付不明の記事は期間指定時には除外する（Streamlit 版と同じ挙動）。
        result = [i for i in result if i.published and _aware(i.published) >= cutoff]

    if query:
        q = query.lower()
        result = [i for i in result if q in i.title.lower() or q in i.summary.lower()]

    return result


def sort_items(items: list[FeedItem], order: str) -> list[FeedItem]:
    if order == "重要度順":
        scored = [i for i in items if i.score is not None]
        unscored = [i for i in items if i.score is None]
        scored.sort(key=lambda i: i.score, reverse=True)
        return scored + unscored
    dated = [i for i in items if i.published is not None]
    undated = [i for i in items if i.published is None]
    dated.sort(key=lambda i: _aware(i.published), reverse=(order == "新しい順"))
    return dated + undated


def is_podcast(item: FeedItem) -> bool:
    return bool(
        item.enclosure_url
        and item.enclosure_type
        and ("audio" in item.enclosure_type or "video" in item.enclosure_type)
    )
