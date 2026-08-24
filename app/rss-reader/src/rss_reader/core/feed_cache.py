import hashlib
import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..config import FEED_CACHE_DIR as CACHE_DIR
from .models import FeedItem, FeedMeta

# 新着ページは全フィード（約1,800記事 / 1.9MB）を読むため、mtime をキーに
# パース済み JSON をプロセス内に持つ。ファイルが書き換わると自動で無効化される。
_memo: dict[Path, tuple[float, dict]] = {}
_memo_lock = threading.Lock()


def _path(url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _read(p: Path) -> dict | None:
    """Return the cache file's parsed JSON, reusing the memo when unchanged."""
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    with _memo_lock:
        hit = _memo.get(p)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None
    with _memo_lock:
        _memo[p] = (mtime, data)
    return data


def _serialize_item(item: FeedItem) -> dict:
    d = asdict(item)
    d["published"] = item.published.isoformat() if item.published else None
    # score / score_parts はリクエストごとに計算し直す派生データ
    d.pop("score_parts", None)
    return d


def _deserialize_item(d: dict) -> FeedItem:
    pub = d.get("published")
    return FeedItem(
        title=d["title"],
        link=d["link"],
        published=datetime.fromisoformat(pub) if pub else None,
        summary=d["summary"],
        feed_url=d["feed_url"],
        feed_title=d["feed_title"],
        enclosure_url=d.get("enclosure_url"),
        enclosure_type=d.get("enclosure_type"),
        duration=d.get("duration"),
        episode_number=d.get("episode_number"),
        image_url=d.get("image_url"),
        author=d.get("author"),
        media_type=d.get("media_type", ""),
        score=d.get("score"),
    )


def _deserialize_meta(d: dict) -> FeedMeta:
    return FeedMeta(
        title=d["title"],
        description=d["description"],
        url=d["url"],
        site_url=d.get("site_url", ""),
        image_url=d.get("image_url", ""),
        media_type=d.get("media_type", ""),
        feed_authors=d.get("feed_authors", []),
    )


def load(url: str) -> tuple[FeedMeta, list[FeedItem], datetime] | None:
    data = _read(_path(url))
    if data is None:
        return None
    try:
        meta = _deserialize_meta(data["meta"])
        # 呼び出し側が score を書き込むので、毎回新しいインスタンスを組み立てる。
        items = [_deserialize_item(d) for d in data["items"]]
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        return meta, items, fetched_at
    except Exception:
        return None


def load_meta(url: str) -> tuple[FeedMeta, datetime] | None:
    data = _read(_path(url))
    if data is None:
        return None
    try:
        meta = _deserialize_meta(data["meta"])
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        return meta, fetched_at
    except Exception:
        return None


def save(url: str, meta: FeedMeta, items: list[FeedItem]) -> datetime:
    fetched_at = datetime.now(timezone.utc)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(url)
    tmp = p.with_suffix(".tmp")
    payload = {
        "url": url,
        "fetched_at": fetched_at.isoformat(),
        "meta": asdict(meta),
        "items": [_serialize_item(i) for i in items],
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(tmp, p)
    return fetched_at


def remove(url: str) -> None:
    p = _path(url)
    with _memo_lock:
        _memo.pop(p, None)
    if p.exists():
        p.unlink()


def fetched_at(url: str) -> datetime | None:
    data = _read(_path(url))
    if data is None:
        return None
    try:
        return datetime.fromisoformat(data["fetched_at"])
    except Exception:
        return None


def content_revision(urls: list[str]) -> tuple[str, int]:
    """購読中フィードの記事構成を表す指紋と、その総件数。

    画面の自動反映用。``save()`` は新着がゼロでも ``fetched_at`` を書き換える
    ので、ファイルの mtime では「取得した」ことしか判らない。毎時の更新の
    たびに一覧を差し替えるのは無駄なうえ、「新着」と言えば嘘になる。記事の
    リンクそのものから指紋を作れば、中身が変わった回だけ拾える。

    ``_read`` がメモ化しているので、2回目以降の実コストは39ファイルの stat と
    リンク文字列のハッシュ計算だけになる。
    """
    h = hashlib.sha1()
    total = 0
    for url in sorted(urls):
        data = _read(_path(url))
        if data is None:
            continue
        for item in data.get("items", []):
            h.update(str(item.get("link", "")).encode())
            h.update(b"\0")
            total += 1
    return h.hexdigest()[:16], total
