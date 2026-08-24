"""Tests for the content fingerprint that drives the browser auto-refresh.

開いたままの一覧に新着を出すため、ブラウザは ``/api/feed-state`` を毎分見て
指紋が変わった回だけ差し替える。ここで固定するのは「取得しただけでは変わらない」
こと。``feed_cache.save()`` は新着ゼロでも ``fetched_at`` を書き換えるので、
ファイルの mtime を指紋にすると毎時の更新のたびに一覧が差し替わり、「新着」と
言えば嘘になる。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from rss_reader.app import app
from rss_reader.core import feed_cache
from rss_reader.core.models import FeedItem, FeedMeta
from rss_reader.core import persistence


URL = "https://example.com/feed"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_cache, "CACHE_DIR", tmp_path / "feed_cache")
    monkeypatch.setattr(persistence, "DATA_FILE", tmp_path / "feeds.json")
    feed_cache._memo.clear()


def _item(link: str) -> FeedItem:
    return FeedItem(
        title=link,
        link=link,
        published=datetime(2026, 8, 24, tzinfo=timezone.utc),
        summary="",
        feed_url=URL,
        feed_title="Example",
    )


def _save(links: list[str]) -> None:
    meta = FeedMeta(title="Example", description="", url=URL)
    feed_cache.save(URL, meta, [_item(link) for link in links])
    # ``_read`` のメモ化は mtime キーで、この環境のファイル時刻の分解能は
    # テスト内の連続した保存を区別できないほど粗い（実測で同一値）。消さないと
    # 指紋ではなくキャッシュヒットを見ることになり、何も固定できない。
    feed_cache._memo.clear()


def test_refetch_without_new_items_keeps_the_same_revision():
    _save(["a", "b"])
    before = feed_cache.content_revision([URL])
    _save(["a", "b"])
    assert feed_cache.content_revision([URL]) == before


def test_new_article_changes_the_revision_and_the_count():
    _save(["a", "b"])
    rev, total = feed_cache.content_revision([URL])
    _save(["c", "a", "b"])
    new_rev, new_total = feed_cache.content_revision([URL])
    assert new_rev != rev
    assert (total, new_total) == (2, 3)


def test_feeds_without_a_cache_file_are_skipped():
    _save(["a"])
    assert feed_cache.content_revision([URL, "https://example.org/never-fetched"]) \
        == feed_cache.content_revision([URL])


def test_endpoint_reports_the_subscribed_feeds():
    persistence.FeedStore().save([URL])
    _save(["a", "b"])
    body = TestClient(app).get("/api/feed-state").json()
    assert body == {
        "revision": feed_cache.content_revision([URL])[0],
        "items": 2,
    }
