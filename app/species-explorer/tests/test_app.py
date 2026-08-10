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


def test_index_has_additional_shooting_guide_for_uncertain_results():
    response = client.get("/")
    assert response.status_code == 200
    assert "function shootingGuide(data)" in response.text
    assert '["taxonomy_only","uncertain"]' in response.text
    assert "追加撮影ガイド" in response.text
    assert "candidate.evidence_gaps" in response.text
    assert ".slice(0,5)" in response.text
    assert 'id="addPhotos"' in response.text


def test_index_links_to_settings():
    response = client.get("/")
    assert 'href="/settings"' in response.text
    assert 'id="historyPanel"' in response.text
    assert 'indexedDB.open("species-history",1)' in response.text
    assert 'slice(50)' in response.text
    assert 'gps.latitude.toFixed(4)' in response.text
    assert 'id="clearHistory"' in response.text
    assert 'id="historyLightbox"' in response.text
    assert 'class="history-image-button"' in response.text
    assert 'showHistoryImage' in response.text
    assert 'historyImageUrls.forEach(URL.revokeObjectURL)' in response.text
    assert '960/Math.max(bitmap.width,bitmap.height)' in response.text
    assert 'model:data.model||""' in response.text
    assert 'resultMeta:{strictMode:' in response.text
    assert 'historyCandidateHtml' in response.text
    assert "写真上の観察点" in response.text
    assert "類似種との識別点" in response.text
    assert "確証がない理由" in response.text
    assert "雌雄推定の根拠" in response.text
    assert "使用モデル：" in response.text
    assert 'return "種候補"' in response.text
    assert 'return "属候補"' in response.text
    assert 'return "科候補"' in response.text
    assert "historyAffiliateLink(entry)" in response.text
    assert 'rel="sponsored noopener noreferrer"' in response.text
    assert "広告 · Amazonで" in response.text
    assert "if(!affiliate?.enabled)return" in response.text
    assert 'OpenStreetMap contributors' in response.text
    assert "雌雄推定" in response.text
    assert "Animal Diversity Web" in response.text
    assert "Cornell All About Birds" in response.text
    assert "FishBase" in response.text
    assert "AmphibiaWeb" in response.text
    assert "Reptile Database" in response.text
    assert all("history" not in route.path for route in main.app.routes if route.path.startswith("/api/"))


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
    assert "Ollama公式ガイド" in response.text
    assert "https://platform.openai.com/api-keys" in response.text
    assert "https://console.anthropic.com/settings/keys" in response.text
    assert "https://aistudio.google.com/app/apikey" in response.text
    assert "https://my.plantnet.org/" in response.text
    assert "ChatGPTの月額契約とは別" in response.text
    assert "Claudeの月額契約とは別" in response.text
    assert "rotatingAffiliateLink(data.candidates,data.category)" in client.get("/").text
    assert "loadAmazonProducts()" in client.get("/").text
    assert "position:fixed" not in client.get("/").text
    assert "position:sticky" not in client.get("/").text
    assert 'id="reset-affiliate-visibility"' not in response.text
    index = client.get("/").text
    assert 'id="gpsButton"' in index
    assert "requestCurrentLocation(true)" in index
    assert 'gps?.source!=="exif"' in index
    assert 'source:"current"' in index
    assert "画像選択時に現在地を取得します" in index
    assert "識別AIへは送らず" in index
    assert "採取可否：確認が必要" in index
    assert "食用可否：このアプリでは判定しません" in index
    assert 'fd.append("latitude"' not in index
    assert 'fd.append("longitude"' not in index
    assert "species-hide-affiliate" not in response.text
    assert "species-hide-affiliate" not in index
    assert "gpt-5.6-sol" not in response.text


def test_affiliate_click_redirects_and_records_metrics():
    main.config_store.save(
        provider="local", models={}, api_keys={}, delete_keys=[],
        affiliate={"title": "関連商品", "url": "https://www.amazon.co.jp/s?k={query}&tag=test-22", "enabled": True},
    )
    impression = client.post("/api/affiliate/impression")
    click = client.get("/affiliate/click?q=タンポポ", follow_redirects=False)
    assert impression.status_code == 200
    assert click.status_code == 302
    assert "%E3%82%BF%E3%83%B3%E3%83%9D%E3%83%9D" in click.headers["location"]
    assert main.config_store.public()["affiliate"]["metrics"] == {"impressions": 1, "clicks": 1}


def test_affiliate_is_absent_until_configured():
    assert client.post("/api/affiliate/impression").status_code == 404
    assert client.get("/affiliate/click", follow_redirects=False).status_code == 404


def test_amazon_products_endpoint_uses_verified_query(monkeypatch):
    monkeypatch.setattr(main.config_store, "load", lambda: {
        "affiliate": {"product_enabled": True, "partner_tag": "test-22", "limit": 4},
        "api_keys": {"amazon_creators_id": "credential", "amazon_creators_secret": "secret"},
    })
    seen = {}
    def fake_search(query, credential, secret, partner_tag, limit):
        seen.update(query=query, credential=credential, secret=secret, partner_tag=partner_tag, limit=limit)
        return [{"title": "タンポポ図鑑", "url": "https://www.amazon.co.jp/dp/B000000001?tag=test-22", "image": "https://images.example/item.jpg"}]
    monkeypatch.setattr(main.creators_api, "search_products", fake_search)
    response = client.get("/api/amazon/products?q=タンポポ")
    assert response.status_code == 200
    assert response.json()["products"][0]["title"] == "タンポポ図鑑"
    assert seen == {"query": "タンポポ", "credential": "credential", "secret": "secret", "partner_tag": "test-22", "limit": 4}


def test_amazon_product_endpoint_is_disabled_without_configuration():
    assert client.get("/api/amazon/products?q=タンポポ").status_code == 404


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
        "ollama_url": "http://localhost:11434",
        "location": "東京都 高尾山",
        "observed_date": "2026-08-09",
        "size": "約5cm",
    }


def test_photo_metadata_reads_exif_before_identification():
    source = io.BytesIO()
    exif = Image.Exif()
    exif[36867] = "2024:11:12 08:09:10"
    Image.new("RGB", (2, 2), "green").save(source, "JPEG", exif=exif)

    response = client.post(
        "/api/photo-metadata",
        files={"files": ("photo.jpg", source.getvalue(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {"observed_date": "2024-11-12"}


def test_identify_uses_exif_date_when_form_date_is_empty(monkeypatch):
    source = io.BytesIO()
    exif = Image.Exif()
    exif[36867] = "2024:11:12 08:09:10"
    Image.new("RGB", (2, 2), "green").save(source, "JPEG", exif=exif)
    seen = {}

    def fake_identify(images, model, **context):
        seen.update(context)
        return {"category": "植物", "summary": "", "candidates": []}

    monkeypatch.setattr(main.vision, "identify", fake_identify)
    response = client.post(
        "/identify",
        files={"files": ("photo.jpg", source.getvalue(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert seen["observed_date"] == "2024-11-12"
    assert response.json()["photo_metadata"]["observed_date"] == "2024-11-12"





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


def test_settings_page_allows_custom_local_llm_url():
    response = client.get("/settings")
    assert response.status_code == 200
    assert 'id="local-llm-url"' in response.text
    assert 'local_llm:{url:' in response.text
    assert 'id="active-provider"' in response.text
    assert response.text.count('<details class="panel"') == 2
    assert 'id="save-button"' in response.text
    assert 'class="message" id="message" aria-live="polite"' in response.text


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


def test_security_headers_are_applied():
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["permissions-policy"] == "camera=(self), geolocation=(self)"


def test_public_mode_hides_server_secrets_and_blocks_settings_write(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["public_mode"] is True
    assert response.json()["local_llm"] == {"url": ""}
    assert not any(response.json()["api_key_configured"].values())

    write = client.post("/api/settings", json={
        "provider": "local", "models": {}, "api_keys": {}, "delete_keys": [],
    })
    assert write.status_code == 403


def test_public_mode_uses_request_key_without_persisting_it(monkeypatch):
    source = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(source, "JPEG")
    seen = {}
    settings = {
        "provider": "local",
        "models": {"local": "gemma4:12b", "gemini": "gemini-3.6-flash"},
        "local_llm": {"url": "http://operator-ollama:11434"},
        "api_keys": {},
    }
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main.config_store, "load", lambda: settings)
    monkeypatch.setattr(main.config_store, "model_catalog", lambda *args: ({
        "local": [{"id": "gemma4:12b"}],
        "openai": [], "anthropic": [],
        "gemini": [{"id": "gemini-3.6-flash"}],
    }, []))

    def fake_identify(images, api_key, model, **context):
        seen.update(api_key=api_key, model=model)
        return {"category": "植物", "summary": "", "candidates": [], "provider": "gemini"}

    monkeypatch.setattr(main.vision, "identify_gemini", fake_identify)
    response = client.post("/identify", files={
        "file": ("photo.jpg", source.getvalue(), "image/jpeg")
    }, data={
        "request_provider": "gemini",
        "request_model": "gemini-3.6-flash",
        "request_api_key": "browser-session-secret",
    })
    assert response.status_code == 200
    assert seen == {"api_key": "browser-session-secret", "model": "gemini-3.6-flash"}
    assert "browser-session-secret" not in response.text
    assert settings["api_keys"] == {}


def test_public_mode_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "PUBLIC_LOCAL_ENABLED", True)
    monkeypatch.setattr(main.config_store, "model_catalog", lambda *args: ({
        "local": [{"id": "gemma4:12b"}], "openai": [], "anthropic": [], "gemini": [],
    }, []))
    response = client.post("/identify", data={
        "request_provider": "local", "request_model": "attacker-model",
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "モデルを選び直してください"


def test_public_settings_ui_keeps_keys_in_tab_session():
    page = client.get("/settings").text
    index = client.get("/").text
    assert "function setupPublicSettings(data)" in page
    assert 'sessionStorage.setItem("species-key-"+name' in page
    assert "APIキーはこのブラウザタブだけに保存" in page
    assert 'fd.append("request_api_key"' in index
    assert 'fd.append("request_model"' in index


def test_public_mode_disables_operator_local_llm_by_default(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "PUBLIC_LOCAL_ENABLED", False)
    response = client.get("/api/settings")
    assert response.json()["provider"] == "gemini"
    assert response.json()["available_models"]["local"] == []


def test_rate_limit_returns_retry_after():
    main._RATE_BUCKETS.clear()
    request = type("FakeRequest", (), {
        "client": type("FakeClient", (), {"host": "rate-test"})()
    })()
    main._rate_limit(request, "test", 2, 30)
    main._rate_limit(request, "test", 2, 30)
    with pytest.raises(main.HTTPException) as caught:
        main._rate_limit(request, "test", 2, 30)
    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "30"}
    main._RATE_BUCKETS.clear()


def test_legal_pages_disclose_data_handling_and_contact():
    privacy = client.get("/privacy")
    terms = client.get("/terms")
    assert privacy.status_code == 200
    assert terms.status_code == 200
    assert "APIキーはブラウザのsessionStorage" in privacy.text
    assert "OpenAI、Anthropic、Google GeminiまたはPl@ntNet" in privacy.text
    assert "Tailscale Funnel" in privacy.text
    assert "https://lit.link/ats030_main" in privacy.text
    assert "運営者プロフィール" in privacy.text
    assert "食用・毒性・採取許可" in terms.text
    assert "外部AIの利用料金" in terms.text


def test_every_user_page_links_to_legal_pages():
    for path in ("/", "/settings", "/history"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'href="/privacy"' in page.text
        assert 'href="/terms"' in page.text


def test_public_beta_forces_affiliate_features_off(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "PUBLIC_AFFILIATE_ENABLED", False)
    settings = client.get("/api/settings").json()
    assert settings["affiliate"]["enabled"] is False
    assert settings["affiliate"]["url"] == ""
    assert settings["affiliate"]["product_enabled"] is False
    assert settings["affiliate"]["creators_api_configured"] is False
    assert client.post("/api/affiliate/impression").status_code == 404
    assert client.post("/api/affiliate/click").status_code == 404
    assert client.get("/affiliate/click?q=test", follow_redirects=False).status_code == 404
    assert client.get("/api/amazon/products?q=test").status_code == 404


def test_private_mode_keeps_operator_affiliate_configuration(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", False)
    main.config_store.save(
        provider="local", models={}, api_keys={}, delete_keys=[],
        affiliate={"title": "関連商品", "url": "https://www.amazon.co.jp/s?k={query}&tag=test-22", "enabled": True},
    )
    assert client.get("/api/settings").json()["affiliate"]["enabled"] is True
