import json
import os
from dataclasses import asdict, dataclass, field

from ..config import BOOKMARKS_FILE


@dataclass
class Bookmark:
    feed_url: str
    feed_title: str
    description: str
    bookmarked_at: str
    tags: list[str]
    site_url: str = ""
    image_url: str = ""
    media_type: str = ""
    authors: list[str] = field(default_factory=list)
    item_titles: list[str] = field(default_factory=list)


class BookmarkStore:
    def load(self) -> list[Bookmark]:
        if not BOOKMARKS_FILE.exists():
            return []
        try:
            data = json.loads(BOOKMARKS_FILE.read_text())
            return [
                Bookmark(
                    feed_url=b["feed_url"],
                    feed_title=b["feed_title"],
                    description=b["description"],
                    bookmarked_at=b["bookmarked_at"],
                    tags=b["tags"],
                    site_url=b.get("site_url", ""),
                    image_url=b.get("image_url", ""),
                    media_type=b.get("media_type", ""),
                    authors=b.get("authors", []),
                    item_titles=b.get("item_titles", []),
                )
                for b in data.get("bookmarks", [])
            ]
        except Exception:
            return []

    def save(self, bookmarks: list[Bookmark]) -> None:
        BOOKMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BOOKMARKS_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"bookmarks": [asdict(b) for b in bookmarks]},
                       ensure_ascii=False, indent=2)
        )
        os.replace(tmp, BOOKMARKS_FILE)

    def add(self, bookmark: Bookmark) -> None:
        bookmarks = [b for b in self.load() if b.feed_url != bookmark.feed_url]
        bookmarks.insert(0, bookmark)
        self.save(bookmarks)

    def remove(self, feed_url: str) -> None:
        self.save([b for b in self.load() if b.feed_url != feed_url])

    def is_bookmarked(self, feed_url: str) -> bool:
        return any(b.feed_url == feed_url for b in self.load())

    def all_tags(self) -> list[str]:
        tags: set[str] = set()
        for b in self.load():
            tags.update(b.tags)
        return sorted(tags)
