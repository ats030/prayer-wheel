import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
import main


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(main.config_store, "SETTINGS_PATH", tmp_path / "settings.json")


def test_health_is_local():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["local_processing"] is True


def test_rejects_non_image():
    response = client.post("/identify", files={"file": ("note.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_index_has_camera_capture():
    response = client.get("/")
    assert response.status_code == 200
    assert 'capture="environment"' in response.text


def test_index_links_to_settings():
    response = client.get("/")
    assert 'href="/settings"' in response.text


def test_settings_page_enables_all_providers():
    response = client.get("/settings")
    assert response.status_code == 200
    assert 'href="/"' in response.text
    assert "OpenAI API" in response.text
    assert "Anthropic API" in response.text
    assert "準備中" not in response.text
    assert 'value="openai"' in response.text
    assert 'value="anthropic"' in response.text
    assert 'id="settingsForm"' in response.text
    assert "gpt-5.6-sol" not in response.text


def test_external_provider_requires_api_key(monkeypatch):
    monkeypatch.setattr(main.config_store, "load", lambda: {"provider": "openai", "models": {"openai": "gpt-5.6-luna"}, "api_keys": {}})
    response = client.post(
        "/identify",
        files={"file": ("photo.jpg", b"not-read", "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "設定画面でAPIキーを登録してください"


def test_openai_provider_dispatches_without_persisting_key(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    seen = {}

    def fake_identify(image_bytes, api_key, model):
        seen["model"] = model
        seen["api_key"] = api_key
        return {"category": "植物", "summary": "", "candidates": [], "provider": "openai"}

    monkeypatch.setattr(main.vision, "identify_openai", fake_identify)
    monkeypatch.setattr(main.config_store, "load", lambda: {"provider": "openai", "models": {"openai": "gpt-5.6-terra"}, "api_keys": {"openai": "temporary-secret"}})
    response = client.post(
        "/identify",
        files={"file": ("photo.jpg", source.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert seen["api_key"] == "temporary-secret"
    assert seen["model"] == "gpt-5.6-terra"



def test_settings_api_saves_model_without_returning_key():
    response = client.post("/api/settings", json={
        "provider": "openai",
        "models": {"openai": "gpt-5.6-terra"},
        "api_keys": {"openai": "write-only-secret"},
        "delete_keys": [],
    })
    assert response.status_code == 200
    assert response.json()["models"]["openai"] == "gpt-5.6-terra"
    assert response.json()["api_key_configured"]["openai"] is True
    assert "write-only-secret" not in response.text
