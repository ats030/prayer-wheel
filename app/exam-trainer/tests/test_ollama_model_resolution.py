"""モデル名をサーバーの一覧に合わせて解決すること (ats030-epm5)。

localhost:11434 は Open WebUI 互換のプロキシで、モデル名を一覧と厳密に照合する。
本物の Ollama は "nomic-embed-text" を ":latest" へ解決するが、このプロキシはしない。
そのため embed() だけが HTTP 400 "Model 'nomic-embed-text' was not found" で落ち、
意味的重複判定が完全一致へ降格していた。チャット側は gemma4:31b のようにタグ付きで
設定されていたので影響が出ていなかった。

失敗しても落とさない (fail-soft)。解決できなければ設定値のまま投げる。
"""

import pytest

from exam_trainer import ollama_client


@pytest.fixture(autouse=True)
def clear_cache():
    ollama_client._MODEL_NAME_CACHE.clear()
    yield
    ollama_client._MODEL_NAME_CACHE.clear()


def _tags(monkeypatch, names):
    monkeypatch.setattr(ollama_client, "_list_model_names", lambda: names)


def test_bare_name_resolves_to_the_tagged_one(monkeypatch):
    _tags(monkeypatch, ["gemma4:31b", "nomic-embed-text:latest"])
    assert ollama_client.resolve_model("nomic-embed-text") == "nomic-embed-text:latest"


def test_exact_name_is_left_alone(monkeypatch):
    _tags(monkeypatch, ["gemma4:31b", "nomic-embed-text:latest"])
    assert ollama_client.resolve_model("gemma4:31b") == "gemma4:31b"


def test_non_latest_tag_is_found(monkeypatch):
    """:latest とは限らない。前方一致で1件に決まるならそれを使う"""
    _tags(monkeypatch, ["nomic-embed-text:v1.5"])
    assert ollama_client.resolve_model("nomic-embed-text") == "nomic-embed-text:v1.5"


def test_ambiguous_prefix_prefers_latest(monkeypatch):
    _tags(monkeypatch, ["gemma4:12b", "gemma4:31b", "gemma4:latest"])
    assert ollama_client.resolve_model("gemma4") == "gemma4:latest"


def test_ambiguous_prefix_without_latest_is_left_alone(monkeypatch):
    """どれを指しているか決められないなら勝手に選ばない"""
    _tags(monkeypatch, ["gemma4:12b", "gemma4:31b"])
    assert ollama_client.resolve_model("gemma4") == "gemma4"


def test_unknown_model_is_left_alone(monkeypatch):
    _tags(monkeypatch, ["gemma4:31b"])
    assert ollama_client.resolve_model("missing-model") == "missing-model"


def test_listing_failure_is_fail_soft(monkeypatch):
    def explode():
        raise RuntimeError("ollama down")

    monkeypatch.setattr(ollama_client, "_list_model_names", explode)
    assert ollama_client.resolve_model("nomic-embed-text") == "nomic-embed-text"


def test_resolution_is_cached(monkeypatch):
    calls = []

    def counting():
        calls.append(1)
        return ["nomic-embed-text:latest"]

    monkeypatch.setattr(ollama_client, "_list_model_names", counting)
    ollama_client.resolve_model("nomic-embed-text")
    ollama_client.resolve_model("nomic-embed-text")
    assert len(calls) == 1


def test_embed_sends_the_resolved_name(monkeypatch):
    sent = {}

    def fake_post(path, payload):
        sent["path"] = path
        sent["payload"] = payload
        return {"embedding": [0.1, 0.2]}

    _tags(monkeypatch, ["nomic-embed-text:latest"])
    monkeypatch.setattr(ollama_client, "_post", fake_post)
    vector = ollama_client.embed("テスト", model="nomic-embed-text")

    assert vector == [0.1, 0.2]
    assert sent["payload"]["model"] == "nomic-embed-text:latest"
