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
    assert "もう1枚撮ると、はっきりします" in response.text
    assert "candidate.evidence_gaps" in response.text
    assert ".slice(0,5)" in response.text
    assert 'id="addPhotos"' in response.text


def test_index_saves_history_but_does_not_render_it():
    """記録の作成はトップが担い、閲覧は /history だけが担う。"""
    response = client.get("/")
    assert 'href="/settings"' in response.text
    assert 'href="/history"' in response.text
    assert 'indexedDB.open("species-history",1)' in response.text
    assert 'slice(50)' in response.text
    assert 'gps.latitude.toFixed(4)' in response.text
    assert '960/Math.max(bitmap.width,bitmap.height)' in response.text
    assert 'model:data.model||""' in response.text
    assert 'resultMeta:{strictMode:' in response.text
    # 表示専用の重複実装を持たないこと（隠れたまま到達できない実装を再び作らない）
    for gone in ["historyPanel", "historyToggle", "renderHistoryList", "historyLightbox",
                 "historyCandidateHtml", "historyAffiliateLink", "historyMessage"]:
        assert gone not in response.text, gone
    # 保存に失敗したら、隠れた要素ではなく利用者が見ている場所へ出す
    assert 'saveHistory(data).catch(error=>showStatus(' in response.text
    assert "この端末の記録には保存できませんでした" in response.text
    assert all("history" not in route.path for route in main.app.routes if route.path.startswith("/api/"))


def test_index_result_view_keeps_its_own_labels():
    response = client.get("/")
    assert "写真から見つけた特徴" in response.text
    assert "似ている種との見分け方" in response.text
    assert "決め手が足りない理由" in response.text
    assert 'return "種の候補"' in response.text
    assert 'return "属（近いなかま）の候補"' in response.text
    assert 'return "科（大きなグループ）の候補"' in response.text
    assert 'rel="sponsored noopener noreferrer"' in response.text
    assert "広告 · Amazonで" in response.text
    assert "オス・メスの推測" in response.text
    for selector in [".sex-result{", ".sex-evidence{", ".animal-references{"]:
        assert selector in response.text, selector
    for site in ["Animal Diversity Web", "Cornell All About Birds", "FishBase",
                 "AmphibiaWeb", "Reptile Database"]:
        assert site in response.text, site


def test_history_page_renders_saved_records():
    page = client.get("/history").text
    assert 'id="clearHistory"' not in page
    assert 'id="clear"' in page
    assert "fullCandidate" in page
    assert "写真から見つけた特徴（AI抽出・未確認）" in page
    assert "似ている種との見分け方" in page
    assert "決め手が足りない理由" in page
    assert 'evidence("そう考えた理由",c.sex_evidence)' in page
    assert "使ったAI：" in page
    assert 'return "種の候補"' not in page  # /history は自前のラベル表を持つ
    assert "属（近いなかま）の候補" in page
    assert "historyAffiliateLink" not in page
    assert "広告 · Amazonで" in page
    assert 'OpenStreetMap contributors' in page


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
    assert "写真を選ぶと現在地を取得します" in index
    assert "AIへは送らず" in index
    assert "持ち帰ってよいか：確認が必要" in index
    assert "食べられるか：判定しません" in index
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


def test_all_pages_use_light_first_theme_with_dark_fallback():
    for path in ["/", "/settings", "/history", "/privacy", "/terms"]:
        page = client.get(path).text
        assert "color-scheme:light dark" in page, path
        assert "@media(prefers-color-scheme:dark)" in page, path
        assert "color-scheme:dark;" not in page, path
        assert "#010102" not in page, path
        assert 'content="#f4faf2" media="(prefers-color-scheme: light)"' in page, path


def test_index_states_all_ages_and_layered_safety_warnings():
    index = client.get("/").text
    assert "どなたでも使えます" in index
    assert "年齢を問わず使えますが、小学生以下のお子さんは大人といっしょに使ってください。" in index
    assert "食べられるか：判定しません" in index
    assert "さわってよいか：判定しません" in index
    assert "持ち帰ってよいか：確認が必要" in index
    assert "小さなお子さんが使うときは、大人といっしょに読んでください" in index


def test_terms_and_privacy_cover_all_ages_use():
    terms = client.get("/terms").text
    assert "対象年齢と保護者の方へ" in terms
    assert "年齢制限はなく、どなたでもご利用いただけます" in terms
    assert "契約者ご本人（成年）が行ってください" in terms
    privacy = client.get("/privacy").text
    assert "お子さまの利用" in privacy
    assert "年齢制限を設けていません" in privacy


def test_settings_warns_that_api_keys_are_for_the_account_holder():
    settings = client.get("/settings").text
    assert "大人の方へ" in settings
    assert "設定は契約者ご本人が行ってください" in settings
    assert "アプリの利用に年齢制限はありません。" in settings


def test_theme_toggle_is_available_on_every_page():
    assert client.get("/theme.js").status_code == 200
    script = client.get("/theme.js").text
    assert 'localStorage.getItem("species-theme")' in script or 'var KEY = "species-theme"' in script
    assert 'root.removeAttribute("data-theme")' in script
    assert 'root.setAttribute("data-theme", mode)' in script
    for path in ["/", "/settings", "/history", "/privacy", "/terms"]:
        page = client.get(path).text
        assert '<script src="/theme.js"></script>' in page, path
        assert 'id="themeToggle"' in page, path
        assert ':root[data-theme="dark"]' in page, path
        assert '@media(prefers-color-scheme:dark){:root:not([data-theme="light"])' in page, path


def test_theme_script_loads_before_the_page_body():
    for path in ["/", "/settings", "/history", "/privacy", "/terms"]:
        page = client.get(path).text
        tag_start = page.index('<script src="/theme.js">')
        assert tag_start < page.index("<body"), path
        assert "<style" not in page[:tag_start], path


def test_history_map_is_never_loaded_without_an_explicit_press():
    """位置を含む地図タイルは、利用者が押すまで第三者へ要求しない。"""
    page = client.get("/history").text
    assert "unpkg.com" not in page
    assert '"/vendor/leaflet/leaflet.js"' in page
    assert '"/vendor/leaflet/leaflet.css"' in page
    assert 'id="showMap"' in page
    assert '$("showMap").onclick=showMap' in page
    # 描画は押下ハンドラの中だけ。読み込み時の render() からは呼ばない
    assert "map(entries);$(\"clear\")" not in page
    assert "map(mapEntries)" in page
    assert "「地図を表示」を押したときだけ" in page
    for path in ["/vendor/leaflet/leaflet.js", "/vendor/leaflet/leaflet.css",
                 "/vendor/leaflet/images/marker-icon.png", "/vendor/leaflet/LICENSE"]:
        assert client.get(path).status_code == 200, path
    assert "BSD 2-Clause" in client.get("/vendor/leaflet/LICENSE").text
