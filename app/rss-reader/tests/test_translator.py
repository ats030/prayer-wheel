"""上流障害時に翻訳キャッシュを汚さないことの回帰テスト (ats030-bnrg)。

502/503 を返す期間に原文をそのまま 30 日キャッシュしていたため、上流が復旧しても
未翻訳のまま固定される作りだった。
"""

import diskcache
import pytest

from rss_reader.core import translator


@pytest.fixture
def cache(tmp_path, monkeypatch):
    c = diskcache.Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(translator, "_get_cache", lambda: c)
    monkeypatch.setenv("RSS_TRANSLATE_TO_JA", "1")
    monkeypatch.setenv("OLLAMA_TRANSLATE_MODEL", "dummy:latest")
    return c


ITEMS = [("Hello world", "A short English summary about software.")]


def test_failure_is_not_cached(cache, monkeypatch):
    monkeypatch.setattr(translator, "_request_translation", lambda model, chunk: {})

    assert translator.translate_items_to_japanese(ITEMS) == ITEMS
    assert len(cache) == 0


def test_success_is_cached(cache, monkeypatch):
    monkeypatch.setattr(
        translator,
        "_request_translation",
        lambda model, chunk: {chunk[0][0]: ("こんにちは世界", "ソフトウェアの短い要約。")},
    )

    result = translator.translate_items_to_japanese(ITEMS)
    assert result == [("こんにちは世界", "ソフトウェアの短い要約。")]
    assert cache.get(translator._cache_key(*ITEMS[0])) == ("こんにちは世界", "ソフトウェアの短い要約。")


def test_failed_item_can_be_retried(cache, monkeypatch):
    monkeypatch.setattr(translator, "_request_translation", lambda model, chunk: {})
    translator.translate_items_to_japanese(ITEMS)

    monkeypatch.setattr(
        translator,
        "_request_translation",
        lambda model, chunk: {chunk[0][0]: ("こんにちは世界", "ソフトウェアの短い要約。")},
    )
    assert translator.translate_items_to_japanese(ITEMS) == [
        ("こんにちは世界", "ソフトウェアの短い要約。")
    ]
