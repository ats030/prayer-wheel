import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

import config_store


def test_settings_save_is_private_and_public_response_hides_key(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config_store, "SETTINGS_PATH", path)

    result = config_store.save(
        provider="openai",
        models={"openai": "gpt-5.6-terra"},
        api_keys={"openai": "secret-value"},
        delete_keys=[],
    )

    assert result["provider"] == "openai"
    assert result["models"]["openai"] == "gpt-5.6-terra"
    assert result["api_key_configured"]["openai"] is True
    assert "secret-value" not in str(result)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert config_store.load()["api_keys"]["openai"] == "secret-value"



def test_plantnet_key_is_private_and_independent(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config_store, "SETTINGS_PATH", path)

    result = config_store.save(
        provider="local", models={}, api_keys={"plantnet": "plant-secret"}, delete_keys=[]
    )

    assert result["api_key_configured"]["plantnet"] is True
    assert "plant-secret" not in str(result)
    assert config_store.load()["api_keys"]["plantnet"] == "plant-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_settings_rejects_unknown_model(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    try:
        config_store.save(
            provider="openai",
            models={"openai": "untrusted-model"},
            api_keys={"openai": "secret"},
            delete_keys=[],
        )
    except config_store.SettingsError as exc:
        assert "モデル" in str(exc)
    else:
        raise AssertionError("unknown model was accepted")


def test_settings_can_delete_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    config_store.save(
        provider="openai",
        models={},
        api_keys={"openai": "secret"},
        delete_keys=[],
    )
    result = config_store.save(
        provider="local",
        models={},
        api_keys={},
        delete_keys=["openai"],
    )
    assert result["api_key_configured"]["openai"] is False


def test_affiliate_settings_and_metrics_are_persistent(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    result = config_store.save(
        provider="local", models={}, api_keys={}, delete_keys=[],
        affiliate={"title": "身近な植物図鑑", "url": "https://www.amazon.co.jp/s?k={query}&tag=test-22", "enabled": True},
    )
    assert result["affiliate"]["enabled"] is True
    assert result["affiliate"]["url"] == "https://www.amazon.co.jp/s?k={query}&tag=test-22"
    config_store.record_affiliate("impressions")
    config_store.record_affiliate("clicks")
    assert config_store.public()["affiliate"]["metrics"] == {"impressions": 1, "clicks": 1}
    assert config_store.affiliate_target("タンポポ") == "https://www.amazon.co.jp/s?k=%E3%82%BF%E3%83%B3%E3%83%9D%E3%83%9D&tag=test-22"


def test_affiliate_rejects_non_https_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    try:
        config_store.save(provider="local", models={}, api_keys={}, delete_keys=[], affiliate={
            "title": "図鑑", "url": "javascript:alert(1)", "enabled": True,
        })
    except config_store.SettingsError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("unsafe affiliate URL was accepted")


def test_affiliate_requires_query_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    try:
        config_store.save(provider="local", models={}, api_keys={}, delete_keys=[], affiliate={
            "title": "図鑑", "url": "https://www.amazon.co.jp/books?tag=test-22", "enabled": True,
        })
    except config_store.SettingsError as exc:
        assert "{query}" in str(exc)
    else:
        raise AssertionError("fixed affiliate URL was accepted")


def test_creators_api_credentials_are_write_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    result = config_store.save(provider="local", models={}, delete_keys=[], api_keys={
        "amazon_creators_id": "credential-id", "amazon_creators_secret": "creator-secret",
    }, affiliate={
        "title": "関連商品", "url": "https://www.amazon.co.jp/s?k={query}&tag=test-22",
        "enabled": True, "partner_tag": "test-22", "product_enabled": True,
    })
    assert result["affiliate"]["product_enabled"] is True
    assert result["affiliate"]["creators_api_configured"] is True
    assert "creator-secret" not in str(result)
    assert config_store.load()["api_keys"]["amazon_creators_secret"] == "creator-secret"


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def test_ollama_catalog_only_enables_vision_models(monkeypatch):
    monkeypatch.setattr(
        config_store.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse({"models": [
            {
                "name": "vision-model:latest",
                "capabilities": ["completion", "vision"],
                "details": {"parameter_size": "7B"},
            },
            {
                "name": "text-model:latest",
                "capabilities": ["completion"],
                "details": {"parameter_size": "8B"},
            },
        ]}),
    )
    monkeypatch.setattr(
        config_store.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({
            "capabilities": (
                ["completion", "vision"]
                if kwargs["json"]["model"] == "vision-model:latest"
                else ["completion"]
            )
        }),
    )
    catalog, incompatible = config_store.model_catalog()
    assert catalog["local"] == [{
        "id": "vision-model:latest",
        "label": "vision-model:latest · 7B",
    }]
    assert incompatible == ["text-model:latest"]


def test_ollama_show_recovers_vision_capability_missing_from_tags(monkeypatch):
    monkeypatch.setattr(
        config_store.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse({"models": [{
            "name": "derived-vision:26b",
            "capabilities": ["completion", "tools"],
        }]}),
    )
    monkeypatch.setattr(
        config_store.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({
            "capabilities": ["completion", "vision", "tools"]
        }),
    )

    catalog, incompatible = config_store.model_catalog()

    assert catalog["local"] == [{
        "id": "derived-vision:26b",
        "label": "derived-vision:26b",
    }]
    assert incompatible == []


def test_ollama_outage_keeps_saved_local_model(monkeypatch):
    def unavailable(*args, **kwargs):
        raise config_store.httpx.ConnectError("offline")

    monkeypatch.setattr(config_store.httpx, "get", unavailable)
    catalog, incompatible = config_store.model_catalog("saved-vision:9b")
    assert catalog["local"][0]["id"] == "saved-vision:9b"
    assert incompatible == []


def test_gemini_credentials_are_write_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    result = config_store.save(provider="gemini", models={"gemini": "gemini-3.6-flash"}, api_keys={"gemini": "gemini-secret"}, delete_keys=[])
    assert result["provider"] == "gemini"
    assert result["models"]["gemini"] == "gemini-3.6-flash"
    assert result["api_key_configured"]["gemini"] is True
    assert "gemini-secret" not in str(result)
    assert config_store.load()["api_keys"]["gemini"] == "gemini-secret"


def test_legacy_books_search_url_is_migrated_to_all_categories(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config_store, "SETTINGS_PATH", path)
    path.write_text('{"affiliate":{"title":"関連商品","url":"https://www.amazon.co.jp/s?i=stripbooks\u0026k={query}\u0026tag=test-22","enabled":true}}', encoding="utf-8")
    loaded = config_store.load()
    assert loaded["affiliate"]["url"] == "https://www.amazon.co.jp/s?k={query}" + chr(38) + "tag=test-22"
    assert "図鑑" not in config_store.affiliate_target("タンポポ")
