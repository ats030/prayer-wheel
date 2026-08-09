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
        affiliate={"title": "身近な植物図鑑", "url": "https://amzn.asia/example", "enabled": True},
    )
    assert result["affiliate"]["enabled"] is True
    assert result["affiliate"]["url"] == "https://amzn.asia/example"
    config_store.record_affiliate("impressions")
    config_store.record_affiliate("clicks")
    assert config_store.public()["affiliate"]["metrics"] == {"impressions": 1, "clicks": 1}
    assert config_store.affiliate_target() == "https://amzn.asia/example"


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
