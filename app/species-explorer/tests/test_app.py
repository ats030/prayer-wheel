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
    assert "Google Gemini API" in response.text
    assert "準備中" not in response.text
    assert 'value="openai"' in response.text
    assert 'value="anthropic"' in response.text
    assert 'value="gemini"' in response.text
    assert 'id="settingsForm"' in response.text
    assert "gpt-5.6-sol" not in response.text


def test_affiliate_click_redirects_and_records_metrics():
    main.config_store.save(
        provider="local", models={}, api_keys={}, delete_keys=[],
        affiliate={"title": "野鳥図鑑", "url": "https://www.amazon.co.jp/s?i=stripbooks&k={query}&tag=test-22", "enabled": True},
    )
    impression = client.post("/api/affiliate/impression")
    click = client.get("/affiliate/click?q=タンポポ", follow_redirects=False)
    assert impression.status_code == 200
    assert click.status_code == 302
    assert "%E3%82%BF%E3%83%B3%E3%83%9D%E3%83%9D+%E5%9B%B3%E9%91%91" in click.headers["location"]
    assert main.config_store.public()["affiliate"]["metrics"] == {"impressions": 1, "clicks": 1}


def test_affiliate_is_absent_until_configured():
    assert client.post("/api/affiliate/impression").status_code == 404
    assert client.get("/affiliate/click", follow_redirects=False).status_code == 404


def test_amazon_product_endpoint_uses_verified_query(monkeypatch):
    monkeypatch.setattr(main.config_store, "load", lambda: {
        "affiliate": {"product_enabled": True, "partner_tag": "test-22"},
        "api_keys": {"amazon_creators_id": "credential", "amazon_creators_secret": "secret"},
    })
    seen = {}
    def fake_search(query, credential, secret, partner_tag):
        seen.update(query=query, credential=credential, secret=secret, partner_tag=partner_tag)
        return {"title": "タンポポ図鑑", "url": "https://www.amazon.co.jp/dp/B000000001?tag=test-22", "image": ""}
    monkeypatch.setattr(main.creators_api, "search_book", fake_search)
    response = client.get("/api/amazon/product?q=タンポポ")
    assert response.status_code == 200
    assert response.json()["title"] == "タンポポ図鑑"
    assert seen == {"query": "タンポポ", "credential": "credential", "secret": "secret", "partner_tag": "test-22"}


def test_amazon_product_endpoint_is_disabled_without_configuration():
    assert client.get("/api/amazon/product?q=タンポポ").status_code == 404


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

    def fake_identify(image_bytes, api_key, model, **context):
        seen["images"] = image_bytes
        seen["context"] = context
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
    assert len(seen["images"]) == 1


def test_identify_accepts_three_images_and_context(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    seen = {}

    def fake_identify(images, model, **context):
        seen.update(images=images, model=model, context=context)
        return {"category": "植物", "summary": "", "candidates": []}

    monkeypatch.setattr(main.vision, "identify", fake_identify)
    photos = [("files", (f"photo-{index}.jpg", source.getvalue(), "image/jpeg")) for index in range(3)]
    response = client.post("/identify", files=photos, data={
        "location": "東京都 高尾山",
        "observed_date": "2026-08-09",
        "size": "約5cm",
    })

    assert response.status_code == 200
    assert len(seen["images"]) == 3
    assert seen["context"] == {
        "location": "東京都 高尾山",
        "observed_date": "2026-08-09",
        "size": "約5cm",
    }





def test_plantnet_opt_in_merges_specialist_result(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    monkeypatch.setattr(main.config_store, "load", lambda: {
        "provider": "local",
        "models": {"local": "gemma4:31b"},
        "api_keys": {"plantnet": "plant-secret"},
    })
    monkeypatch.setattr(main.vision, "identify", lambda *args, **kwargs: {
        "category": "植物", "summary": "黄色い花",
        "candidates": [{"scientific_name": "Taraxacum officinale", "traits": ["黄色い花"]}],
        "model": "gemma4:31b", "provider": "local",
    })
    monkeypatch.setattr(main.vision, "identify_plantnet", lambda images, key: {
        "category": "植物", "summary": "専用候補",
        "candidates": [{
            "common_name_ja": "セイヨウタンポポ",
            "scientific_name": "Taraxacum officinale",
            "confidence": 90, "traits": ["専用候補"],
        }],
        "model": "plantnet-test", "provider": "plantnet",
    })

    response = client.post("/identify", files={
        "file": ("photo.jpg", source.getvalue(), "image/jpeg")
    }, data={"use_plantnet": "true"})

    assert response.status_code == 200
    assert response.json()["provider"] == "plantnet"
    assert response.json()["plantnet_used"] is True
    assert response.json()["candidates"][0]["agreement"] == "matched"


def test_plantnet_failure_falls_back_to_vlm_result(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    monkeypatch.setattr(main.config_store, "load", lambda: {
        "provider": "local",
        "models": {"local": "gemma4:31b"},
        "api_keys": {"plantnet": "plant-secret"},
    })
    monkeypatch.setattr(main.vision, "identify", lambda *args, **kwargs: {
        "category": "植物", "summary": "葉", "candidates": [],
        "model": "gemma4:31b", "provider": "local",
    })
    monkeypatch.setattr(
        main.vision, "identify_plantnet",
        lambda *args, **kwargs: (_ for _ in ()).throw(main.vision.VisionError("利用できません")),
    )

    response = client.post("/identify", files={
        "file": ("photo.jpg", source.getvalue(), "image/jpeg")
    }, data={"use_plantnet": "true"})

    assert response.status_code == 200
    assert response.json()["provider"] == "local"
    assert response.json()["plantnet_status"] == "unavailable"


def test_identify_always_runs_strict_evidence_gate(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    monkeypatch.setattr(main.vision, "identify", lambda *args, **kwargs: {
        "category": "植物", "summary": "", "candidates": []
    })
    seen = {}

    def fake_gate(result):
        seen["called"] = True
        result["strict_mode"] = True
        return result

    monkeypatch.setattr(main.vision, "apply_evidence_gate", fake_gate)
    response = client.post("/identify", files={
        "file": ("photo.jpg", source.getvalue(), "image/jpeg")
    })

    assert response.status_code == 200
    assert response.json()["strict_mode"] is True
    assert seen["called"] is True



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


def test_gemini_provider_dispatches_without_exposing_key(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    seen = {}

    def fake_identify(image_bytes, api_key, model, **context):
        seen.update(images=image_bytes, api_key=api_key, model=model, context=context)
        return {"category": "植物", "summary": "", "candidates": [], "provider": "gemini"}

    monkeypatch.setattr(main.vision, "identify_gemini", fake_identify)
    monkeypatch.setattr(main.config_store, "load", lambda: {"provider": "gemini", "models": {"gemini": "gemini-3.6-flash"}, "api_keys": {"gemini": "temporary-gemini-secret"}})
    response = client.post("/identify", files={"file": ("photo.jpg", source.getvalue(), "image/jpeg")})
    assert response.status_code == 200
    assert response.json()["provider"] == "gemini"
    assert seen["api_key"] == "temporary-gemini-secret"
    assert seen["model"] == "gemini-3.6-flash"
    assert len(seen["images"]) == 1
