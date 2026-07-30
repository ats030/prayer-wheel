from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FeedMeta:
    title: str
    description: str
    url: str
    site_url: str = ""
    image_url: str = ""
    media_type: str = ""
    feed_authors: list[str] = field(default_factory=list)


@dataclass
class FeedItem:
    title: str
    link: str
    published: datetime | None
    summary: str
    feed_url: str
    feed_title: str
    enclosure_url: str | None = None
    enclosure_type: str | None = None
    duration: str | None = None
    episode_number: int | None = None
    image_url: str | None = None
    author: str | None = None
    media_type: str = ""
    score: float | None = None
    # スコアの内訳。表示用の派生データなのでキャッシュには保存しない。
    score_parts: dict | None = None
