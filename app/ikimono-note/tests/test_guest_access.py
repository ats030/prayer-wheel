"""Guest access never grants account ownership or operator configuration."""
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "LOGIN_REQUIRED", False)
    monkeypatch.setattr(main.auth, "configured", lambda: True)
    monkeypatch.setattr(main.auth, "read_session", lambda _: None)
    with TestClient(main.app, base_url="http://localhost") as client:
        yield client


def test_guest_pages_and_settings_are_available(client):
    for path in ("/", "/settings", "/history", "/dashboard", "/api/settings"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
    assert "id=\"photos\"" in client.get("/").text or "index.js" in client.get("/").text


def test_guest_cannot_write_operator_settings_or_account_data(client):
    assert client.post("/api/settings", json={"provider": "gemini"}).status_code == 403
    assert client.post("/api/me/delete").status_code == 401
    assert client.post("/api/share").status_code == 401
    assert client.post("/api/share/synthetic/delete").status_code == 401
    assert client.get("/api/unknown").status_code == 401


def test_preview_default_still_requires_google_login(client, monkeypatch):
    monkeypatch.setattr(main, "LOGIN_REQUIRED", True)
    assert client.get("/history", follow_redirects=False).status_code == 303
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/gemini/prepare", json={}).status_code == 401
