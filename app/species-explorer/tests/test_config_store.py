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
    catalog, incompatible = config_store.model_catalog()
    assert catalog["local"] == [{
        "id": "vision-model:latest",
        "label": "vision-model:latest · 7B",
    }]
    assert incompatible == ["text-model:latest"]


def test_ollama_outage_keeps_saved_local_model(monkeypatch):
    def unavailable(*args, **kwargs):
        raise config_store.httpx.ConnectError("offline")

    monkeypatch.setattr(config_store.httpx, "get", unavailable)
    catalog, incompatible = config_store.model_catalog("saved-vision:9b")
    assert catalog["local"][0]["id"] == "saved-vision:9b"
    assert incompatible == []
