"""Tests for the per-feed failure record and the pages that surface it.

取得に失敗し続けるフィードは古い記事を返し続けるだけなので、一覧を見ても
気づけない（実際に61日ぶん古いフィードが放置されていた）。ここで固定するのは
「失敗が永続化されること」と「成功したら消えること」の2点。
"""

from __future__ import annotations

import pytest

from rss_reader.core import feed_status


@pytest.fixture(autouse=True)
def isolated_status(tmp_path, monkeypatch):
    monkeypatch.setattr(feed_status, "STATUS_FILE", tmp_path / "feed_status.json")


URL = "https://example.com/feed"


def test_failure_is_persisted_with_type_and_message():
    feed_status.record_failure(URL, ValueError("boom"))
    entry = feed_status.load()[URL]
    assert entry["last_error"] == "ValueError: boom"
    assert entry["last_attempt"] and entry["failing_since"]


def test_failing_since_survives_repeated_failures():
    """「いつから壊れているか」は最初の失敗時刻のまま。毎回上書きすると経過が消える。"""
    feed_status.record_failure(URL, OSError("first"))
    first = feed_status.load()[URL]["failing_since"]

    feed_status.record_failure(URL, OSError("second"))
    entry = feed_status.load()[URL]
    assert entry["failing_since"] == first
    assert entry["last_attempt"] >= first
    assert entry["last_error"] == "OSError: second"


def test_success_clears_the_entry():
    feed_status.record_failure(URL, OSError("down"))
    feed_status.record_success(URL)
    assert feed_status.load() == {}


def test_success_on_healthy_feed_is_a_no_op():
    feed_status.record_success(URL)
    assert feed_status.load() == {}


def test_long_errors_are_truncated():
    feed_status.record_failure(URL, ValueError("x" * 1000))
    assert len(feed_status.load()[URL]["last_error"]) == 300


def test_missing_file_reads_as_empty():
    assert feed_status.load() == {}


def test_corrupt_file_reads_as_empty():
    feed_status.STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    feed_status.STATUS_FILE.write_text("{ not json")
    assert feed_status.load() == {}


def test_refresh_feed_records_and_clears(monkeypatch):
    """成否の記録は refresh_feed の中。単発更新・追加・全更新のどこからでも通る。"""
    from rss_reader import service

    def boom(url):
        raise OSError("network down")

    monkeypatch.setattr(service, "fetch_bytes", boom)
    with pytest.raises(OSError):
        service.refresh_feed(URL)
    assert URL in feed_status.load()

    monkeypatch.setattr(service, "fetch_bytes", lambda url: (b"<rss/>", "text/xml"))
    monkeypatch.setattr(service, "parse_feed_meta", lambda url, raw: object())
    monkeypatch.setattr(service, "parse_feed", lambda url, raw: [])
    monkeypatch.setattr(service.feed_cache, "save", lambda url, meta, items: None)
    service.refresh_feed(URL)
    assert feed_status.load() == {}


def test_failing_feeds_reports_elapsed_days(monkeypatch):
    from rss_reader import service

    feed_status.record_failure(URL, OSError("down"))
    data = feed_status.load()
    data[URL]["failing_since"] = "2026-07-01T00:00:00+00:00"
    feed_status._save(data)

    monkeypatch.setattr(service, "feed_title", lambda url: "Example")
    result = service.failing_feeds([URL, "https://other.example/feed"])
    assert set(result) == {URL}
    assert result[URL]["days"] > 0
    assert result[URL]["title"] == "Example"


def test_failing_feeds_tolerates_a_broken_timestamp(monkeypatch):
    from rss_reader import service

    feed_status.record_failure(URL, OSError("down"))
    data = feed_status.load()
    data[URL]["failing_since"] = "not-a-date"
    feed_status._save(data)

    monkeypatch.setattr(service, "feed_title", lambda url: "Example")
    assert service.failing_feeds([URL])[URL]["days"] is None
