from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from .classifier import classify_media_type, extract_feed_authors, extract_item_author
from .models import FeedItem, FeedMeta
from .translator import translate_items_to_japanese


def _to_datetime(struct) -> datetime | None:
    if struct is None:
        return None
    try:
        return datetime(*struct[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "lxml").get_text(separator=" ", strip=True)


def _parse_enclosure(entry) -> tuple[str | None, str | None]:
    for enc in entry.get("enclosures", []):
        t = enc.get("type", "")
        if "audio" in t or "video" in t:
            return enc.get("url"), t
    return None, None


def _parse_duration(entry) -> str | None:
    raw = entry.get("itunes_duration")
    if not raw:
        return None
    s = str(raw).strip()
    if ":" in s:
        return s
    try:
        secs = int(s)
        h, rem = divmod(secs, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
    except ValueError:
        return s


def parse_feed_meta(url: str, raw: bytes) -> FeedMeta:
    parsed = feedparser.parse(raw)
    description = _strip_html(
        parsed.feed.get("description") or parsed.feed.get("subtitle", "")
    )
    image_url = (
        parsed.feed.get("image", {}).get("href")
        or parsed.feed.get("image", {}).get("url")
        or parsed.feed.get("itunes_image", {}).get("href")
        or parsed.feed.get("logo")
        or parsed.feed.get("icon")
        or ""
    )
    return FeedMeta(
        title=parsed.feed.get("title", url),
        description=description[:500],
        url=url,
        site_url=parsed.feed.get("link", ""),
        image_url=image_url,
        media_type=classify_media_type(parsed.feed, parsed.entries, url),
        feed_authors=extract_feed_authors(parsed.feed, parsed.entries),
    )


def parse_feed(url: str, raw: bytes) -> list[FeedItem]:
    parsed = feedparser.parse(raw)
    feed_title = parsed.feed.get("title", url)
    feed_image = parsed.feed.get("image", {}).get("href") or \
                 parsed.feed.get("itunes_image", {}).get("href")
    feed_media_type = classify_media_type(parsed.feed, parsed.entries, url)
    entries = []
    for entry in parsed.entries:
        summary = _strip_html(
            entry.get("summary", entry.get("content", [{}])[0].get("value", ""))
        )
        entries.append((entry, entry.get("title", "(タイトルなし)"), summary[:500] if summary else ""))

    translated = translate_items_to_japanese(
        [(title, summary) for _, title, summary in entries]
    )

    items = []
    for (entry, _title, _summary), (title_ja, summary_ja) in zip(entries, translated):
        enc_url, enc_type = _parse_enclosure(entry)
        ep_image = entry.get("itunes_image", {}).get("href") or feed_image
        ep_num = entry.get("itunes_episode")
        items.append(
            FeedItem(
                title=title_ja,
                link=entry.get("link", ""),
                published=_to_datetime(entry.get("published_parsed") or entry.get("updated_parsed")),
                summary=summary_ja,
                feed_url=url,
                feed_title=feed_title,
                enclosure_url=enc_url,
                enclosure_type=enc_type,
                duration=_parse_duration(entry),
                episode_number=int(ep_num) if ep_num else None,
                image_url=ep_image,
                author=extract_item_author(entry),
                media_type=feed_media_type,
            )
        )
    return items
