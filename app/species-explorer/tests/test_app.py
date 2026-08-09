import io
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
import main


client = TestClient(main.app)


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
    assert 'action="/"' in response.text


def test_external_provider_requires_api_key():
    response = client.post(
        "/identify",
        data={"provider": "openai"},
        files={"file": ("photo.jpg", b"not-read", "image/jpeg")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "APIキーを入力してください"


def test_openai_provider_dispatches_without_persisting_key(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    seen = {}

    def fake_identify(image_bytes, api_key):
        seen["api_key"] = api_key
        return {"category": "植物", "summary": "", "candidates": [], "provider": "openai"}

    monkeypatch.setattr(main.vision, "identify_openai", fake_identify)
    response = client.post(
        "/identify",
        data={"provider": "openai", "api_key": "temporary-secret"},
        files={"file": ("photo.jpg", source.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert seen["api_key"] == "temporary-secret"
