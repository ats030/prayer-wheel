import importlib
import os
import re
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
import main


# Host 検証を両モードで効かせているので、実際に許可されるホスト名で叩く
client = TestClient(main.app, base_url="http://localhost")


def page_source(path):
    """HTML と、そのページが読み込む CSS/JS を連結して返す。

    CSP のために資産を外部ファイルへ出したので、実装の中身を見たい検証は
    HTML 単体ではなく「そのページを構成する一式」を対象にする。
    """
    html = client.get(path).text
    parts = [html]
    for asset in re.findall(r'(?:href|src)="(/assets/[^"]+|/theme\.js)"', html):
        parts.append(client.get(asset).text)
    return "\n".join(parts)



@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(main.config_store, "SETTINGS_PATH", tmp_path / "settings.json")


def test_health_is_local():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["local_processing"] is True


def usable_photo(size: tuple[int, int] = (600, 450)) -> bytes:
    """質のふるいを通る写真。一色だと輪郭が無く、ぼけていると見なされる。"""
    image = Image.new("RGB", size, "green")
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if (x // 7 + y // 7) % 2:
                pixels[x, y] = (210, 190, 90)
    return _encode(image)


def _patterned(size: tuple[int, int] = (600, 450)):
    image = Image.new("RGB", size, "green")
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if (x // 7 + y // 7) % 2:
                pixels[x, y] = (210, 190, 90)
    return image


def _encode(image, **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", **kwargs)
    return buffer.getvalue()


def test_rejects_non_image():
    response = client.post("/identify", files={"file": ("note.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_index_has_camera_capture():
    response = client.get("/")
    assert response.status_code == 200
    assert 'capture="environment"' in response.text


def test_index_has_additional_shooting_guide_for_uncertain_results():
    response = client.get("/")
    source = page_source("/")
    assert response.status_code == 200
    assert "function shootingGuide(data)" in source
    assert '["taxonomy_only","uncertain"]' in source
    assert "もう1枚撮ると、はっきりします" in source
    assert "candidate.evidence_gaps" in source
    assert ".slice(0,5)" in source
    assert 'id="addPhotos"' in source


def test_index_saves_history_but_does_not_render_it():
    """記録の作成はトップが担い、閲覧は /history だけが担う。"""
    response = client.get("/")
    source = page_source("/")
    assert 'href="/settings"' in source
    assert 'href="/history"' in source
    assert 'indexedDB.open("species-history",1)' in source
    assert 'slice(50)' in source
    assert 'gps.latitude.toFixed(4)' in source
    assert '960/Math.max(bitmap.width,bitmap.height)' in source
    assert 'model:data.model||""' in source
    assert 'resultMeta:{strictMode:' in source
    # 表示専用の重複実装を持たないこと（隠れたまま到達できない実装を再び作らない）
    for gone in ["historyPanel", "historyToggle", "renderHistoryList", "historyLightbox",
                 "historyCandidateHtml", "historyAffiliateLink", "historyMessage"]:
        assert gone not in source, gone
    # 保存に失敗したら、隠れた要素ではなく利用者が見ている場所へ出す
    assert 'saveHistory(data).catch(error=>showStatus(' in source
    assert "この端末の記録には保存できませんでした" in source
    assert all("history" not in route.path for route in main.app.routes if route.path.startswith("/api/"))


def test_index_result_view_keeps_its_own_labels():
    response = client.get("/")
    source = page_source("/")
    assert "写真から見つけた特徴" in source
    assert "似ている種との見分け方" in source
    assert "決め手が足りない理由" in source
    assert 'return "種の候補"' in source
    assert 'return "属（近いなかま）の候補"' in source
    assert 'return "科（大きなグループ）の候補"' in source
    assert 'rel="sponsored noopener noreferrer"' in source
    assert "広告 · Amazonで" in source
    assert "オス・メスの推測" in source
    for selector in [".sex-result{", ".sex-evidence{", ".animal-references{"]:
        assert selector in source, selector
    for site in ["Animal Diversity Web", "Cornell All About Birds", "FishBase",
                 "AmphibiaWeb", "Reptile Database"]:
        assert site in source, site


def test_history_page_renders_saved_records():
    page = page_source("/history")
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
    assert "topCandidateAffiliateLink(data.candidates,data.category)" in page_source("/")
    assert "loadAmazonProducts()" in page_source("/")
    assert "position:fixed" not in page_source("/")
    assert "position:sticky" not in page_source("/")
    assert 'id="reset-affiliate-visibility"' not in response.text
    index = page_source("/")
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
    def fake_search(query, credential, secret, partner_tag, limit, search_index="All"):
        seen.update(query=query, credential=credential, secret=secret, partner_tag=partner_tag,
                    limit=limit, search_index=search_index)
        return [{"title": "タンポポ図鑑", "url": "https://www.amazon.co.jp/dp/B000000001?tag=test-22", "image": "https://images.example/item.jpg"}]
    monkeypatch.setattr(main.creators_api, "search_products", fake_search)
    response = client.get("/api/amazon/products?q=タンポポ")
    assert response.status_code == 200
    assert response.json()["products"][0]["title"] == "タンポポ図鑑"
    assert seen == {"query": "タンポポ", "credential": "credential", "secret": "secret",
                    "partner_tag": "test-22", "limit": 4, "search_index": "All"}
    # 書籍に絞れる。種名で引くと一般向けの図鑑が上位を占めるため
    client.get("/api/amazon/products?q=タンポポ&index=Books")
    assert seen["search_index"] == "Books"


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
    source.write(usable_photo())
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
    source.write(usable_photo())
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
    source.write(_encode(_patterned(), exif=exif))

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
    source.write(_encode(_patterned(), exif=exif))
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
    source.write(usable_photo())
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
    source.write(usable_photo())
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
    source.write(usable_photo())
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
    source = page_source("/settings")
    assert response.status_code == 200
    assert 'id="local-llm-url"' in source
    assert 'local_llm:{url:' in source
    assert 'id="active-provider"' in source
    # 任意機能の2つ（Pl@ntNet と広告）。持ち出しのクラウド設定も同じ見た目だが別物
    assert 'id="affiliate-panel"' in source and "Pl@ntNet 植物専用の識別" in source
    assert source.count('<details class="panel') >= 2
    assert 'id="save-button"' in source
    assert 'class="message" id="message" aria-live="polite"' in source


def test_gemini_provider_dispatches_without_exposing_key(monkeypatch):
    source = io.BytesIO()
    source.write(usable_photo())
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
    source.write(usable_photo())
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
    page = page_source("/settings")
    index = page_source("/")
    assert "function setupPublicSettings(data)" in page
    assert 'writeApiKey(name,input.value.trim())' in page
    # キーの置き場は利用者が選ぶ。既定はこの端末に残す
    assert "APIキーはこのブラウザの中だけに保存します" in page
    assert 'id="keep-keys"' in page
    assert "keepingKeys()" in page
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
    assert "APIキーはブラウザ内（localStorage または sessionStorage）に保持し" in privacy.text
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
        page = page_source(path)
        assert "color-scheme:light dark" in page, path
        assert "@media(prefers-color-scheme:dark)" in page, path
        assert "color-scheme:dark;" not in page, path
        assert "#010102" not in page, path
        assert 'content="#f4faf2" media="(prefers-color-scheme: light)"' in page, path


def test_index_states_all_ages_and_layered_safety_warnings():
    index = page_source("/")
    assert "年齢を問わず使えますが、小学生以下のお子さんは大人といっしょに使ってください。" in index
    assert "食べられるか：判定しません" in index
    assert "さわってよいか：判定しません" in index
    assert "持ち帰ってよいか：確認が必要" in index
    assert "小さなお子さんが使うときは、大人といっしょに読んでください" in index


def test_terms_and_privacy_cover_all_ages_use():
    terms = page_source("/terms")
    assert "対象年齢と保護者の方へ" in terms
    assert "年齢制限はなく、どなたでもご利用いただけます" in terms
    assert "契約者ご本人（成年）が行ってください" in terms
    privacy = page_source("/privacy")
    assert "お子さまの利用" in privacy
    assert "年齢制限を設けていません" in privacy


def test_settings_warns_that_api_keys_are_for_the_account_holder():
    settings = page_source("/settings")
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
        page = page_source(path)
        assert '<script src="/theme.js"></script>' in page, path
        assert 'id="themeToggle"' in page, path
        assert ':root[data-theme="dark"]' in page, path
        assert '@media(prefers-color-scheme:dark){:root:not([data-theme="light"])' in page, path


def test_theme_script_loads_before_the_page_body():
    for path in ["/", "/settings", "/history", "/privacy", "/terms"]:
        page = page_source(path)
        tag_start = page.index('<script src="/theme.js">')
        assert tag_start < page.index("<body"), path
        assert "<style" not in page[:tag_start], path


def test_history_map_is_never_loaded_without_an_explicit_press():
    """位置を含む地図タイルは、利用者が押すまで第三者へ要求しない。"""
    page = page_source("/history")
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


PAGES = ["/", "/settings", "/history", "/privacy", "/terms"]


def test_csp_is_sent_without_unsafe_keywords():
    for path in PAGES:
        policy = client.get(path).headers["content-security-policy"]
        assert "unsafe-inline" not in policy, path
        assert "unsafe-eval" not in policy, path
        for directive in ["default-src 'self'", "script-src 'self'", "style-src 'self'",
                          "connect-src 'self'", "object-src 'none'", "frame-ancestors 'none'",
                          "base-uri 'none'"]:
            assert directive in policy, (path, directive)
    # 押して初めて出る地図タイルと広告画像だけを外部に許す
    policy = client.get("/").headers["content-security-policy"]
    assert "img-src 'self' blob: https://tile.openstreetmap.org" in policy
    assert "https://*.media-amazon.com" in policy


def test_pages_carry_no_inline_style_or_script():
    """CSP から 'unsafe-inline' を外せる状態を保つ。"""
    for path in PAGES:
        page = client.get(path).text
        assert "<style" not in page, path
        assert 'style="' not in page, path
        assert re.search(r"<script(?![^>]*\ssrc=)", page) is None, path
        for handler in ["onclick=", "onload=", "onerror=", "onsubmit="]:
            assert handler not in page, (path, handler)


def test_page_assets_are_served_locally():
    for name in ["index.css", "index.js", "settings.css", "settings.js",
                 "history.css", "history.js", "privacy.css", "terms.css"]:
        response = client.get(f"/assets/{name}")
        assert response.status_code == 200, name
    assert client.get("/theme.js").status_code == 200
    for path in PAGES:
        page = page_source(path)
        assert "cdn." not in page, path
        assert "unpkg" not in page, path


def test_confidence_meter_avoids_inline_style():
    """幅は style 属性ではなく CSSOM で入れる。属性に戻すと CSP に弾かれる。"""
    index = client.get("/assets/index.js").text
    assert 'data-width=' in index
    assert "bar.style.width=" in index
    assert "applyMeters();" in index
    assert 'style=\\"width:' not in index


def test_api_docs_follow_the_public_mode_switch():
    """公開時は閉じる。CSP下では Swagger UI が CDN を読めず白紙になるため。"""
    assert main.PUBLIC_MODE is False
    assert client.get("/docs").status_code == 200
    public = importlib.reload(main)
    try:
        os.environ["IKIMONO_PUBLIC_MODE"] = "1"
        public = importlib.reload(main)
        assert public.PUBLIC_MODE is True
        assert public.app.docs_url is None and public.app.redoc_url is None
        assert public.app.openapi_url is None
        opened = TestClient(public.app, headers={"host": "localhost"})
        assert opened.get("/docs").status_code == 404
        assert opened.get("/openapi.json").status_code == 404
        assert opened.get("/").status_code == 200
    finally:
        os.environ.pop("IKIMONO_PUBLIC_MODE", None)
        importlib.reload(main)


def test_capture_and_history_screens_use_one_word_per_concept():
    """同じものを別の名前で呼ばない。画面をまたいだ言い換えは利用者を迷わせる。"""
    for path in ["/", "/history"]:
        source = page_source(path)
        visible = source.replace('href="/history"', "")
        for banned, instead in [("履歴", "記録"), ("精度", "誤差"),
                                ("図鑑データベース", "図鑑データ"), ("ローカルLLM", "Ollama"),
                                ("ローカルAI", "Ollama")]:
            assert banned not in visible, (path, banned, instead)
    # 設定のラジオとトップのステータス表示が、同じ提供元を同じ名前で呼ぶ
    assert "Ollama" in page_source("/settings")
    assert 'local:"Ollama"' in client.get("/assets/settings.js").text
    # 撮影画面と記録は共通の呼び名を使う（記録に "local" のような内部IDを出さない）
    assert 'local: "Ollama"' in client.get("/assets/species-links.js").text
    for script in ["/assets/index.js", "/assets/history.js"]:
        assert "providerLabel(" in client.get(script).text, script
    # 設定が引用するチェックボックスのラベルは、実際のラベルと一致する
    label = "植物専用の識別もいっしょに使う"
    assert label in client.get("/").text
    assert label in client.get("/settings").text


def test_privacy_policy_matches_where_deletion_actually_lives():
    privacy = client.get("/privacy").text
    assert "設定画面・履歴画面から利用者が削除できます" not in privacy
    assert "「調べた記録」の画面から、1件ずつ、またはすべてを利用者が削除できます" in privacy
    settings = page_source("/settings")
    assert "すべて削除" not in settings  # 削除は /history だけが持つ
    assert "すべて削除" in page_source("/history")


def test_host_header_is_validated_in_both_modes():
    """設定を書き換えられる運営者用こそ Host 検証が要る。"""
    assert any(m.cls is main.TrustedHostMiddleware for m in main.app.user_middleware)
    assert client.get("/health", headers={"host": "evil.example.com"}).status_code == 400
    assert client.get("/health").status_code == 200


def test_admin_instance_can_save_settings_and_public_one_cannot():
    payload = {"provider": "local", "models": {}, "local_llm": {"url": "http://127.0.0.1:11434"},
               "api_keys": {}, "delete_keys": [], "affiliate": {}}
    assert client.post("/api/settings", json=payload).status_code == 200
    assert main.PUBLIC_MODE is False
    try:
        os.environ["IKIMONO_PUBLIC_MODE"] = "1"
        public = importlib.reload(main)
        opened = TestClient(public.app, base_url="http://localhost")
        assert opened.post("/api/settings", json=payload).status_code == 403
    finally:
        os.environ.pop("IKIMONO_PUBLIC_MODE", None)
        importlib.reload(main)


def test_user_facing_messages_use_the_same_words_as_the_screens():
    """エラー文だけ別の語彙になっていると、同じものが別物に見える。"""
    sources = {name: (Path(__file__).parents[1] / name).read_text(encoding="utf-8")
               for name in ["main.py", "vision.py", "config_store.py", "pipeline.py"]}
    for name, text in sources.items():
        messages = re.findall(r'(?:detail=|VisionError\(|SettingsError\()\s*f?["\']([^"\']{4,})["\']', text)
        joined = "\n".join(messages)
        assert "ローカルLLM" not in joined, name          # 実体を名指しして「Ollama」
        assert "ローカルAI" not in joined, name
        assert "計算資源" not in joined, name              # 画面は「使うAI」
        assert "画像ファイル" not in joined, name          # 画面は「写真」
        assert "画像は" not in joined, name


def test_operator_only_details_stay_out_of_user_messages():
    """環境変数名や内部の数値を画面に出さない。利用者には手の打ちようがない。"""
    text = (Path(__file__).parents[1] / "vision.py").read_text(encoding="utf-8")
    messages = re.findall(r'VisionError\(\s*f?["\']([^"\']{4,})["\']', text)
    for message in messages:
        assert "SPECIES_" not in message, message
        assert "maxOutputTokens" not in message, message
        assert "finishReason" not in message or "{" in message, message


def test_settings_screen_names_each_thing_once():
    page = client.get("/settings").text
    assert "識別に使うAI" not in page      # 「使うAIを選ぶ」に統一
    assert "使うAIを選ぶ" in page
    assert "識別結果に関連商品" not in page  # 結果の呼び名は画面全体で揃える
    # 公開版が別ポートで動いている今、「一般公開に対応していない」は事実と食い違う
    assert "認証のない一般公開には対応していません" not in page
    assert "この画面にはパスワードがありません" in page


def test_screen_differences_are_declared_not_patched_in():
    """運営者用と公開版の差は HTML の data-only で宣言し、body のモードで出し分ける。
    JS で後から隠すと、どこが違うのかコードを追わないと分からない。"""
    page = client.get("/settings").text
    assert 'data-app-mode="operator"' in page  # テストは非公開モードで動く
    assert 'data-show-local="1"' in page
    for declared in ['data-only="operator"', 'data-only="public"', 'data-only="local"']:
        assert declared in page, declared
    rules = client.get("/assets/mode.css").text
    assert 'body[data-app-mode="public"] [data-only="operator"]' in rules
    assert 'body[data-show-local="0"] [data-only="local"]' in rules
    # 表示の出し入れを JS に残さない
    script = client.get("/assets/settings.js").text
    for gone in ['classList.add("hidden")', "security.innerHTML", '$("save-button").textContent']:
        assert gone not in script, gone


def test_both_wordings_ship_in_one_page():
    """同じHTMLに両方の文言を置き、モードで選ぶ。片方だけ直してずれるのを防ぐ。"""
    page = client.get("/settings").text
    assert "変更を保存" in page and "この端末に保存" in page
    assert ">大人の方へ<" in page and ">運営者用<" in page
    assert "APIキーは所有者だけが読めるサーバー設定へ保存し" in page  # 運営者向け
    assert "APIキーはこのブラウザの中だけに保存します" in page            # 公開版向け


def test_operator_settings_keep_every_control():
    """運営者用は据え置き。畳むのは公開版だけ。"""
    page = client.get("/settings").text
    assert main.PUBLIC_MODE is False
    for control in ['value="local"', 'id="local-llm-url"', 'id="affiliate-panel"',
                    'id="affiliate-url"', 'id="key-amazon_creators_id"']:
        assert control in page, control
    assert ">変更を保存<" in page


def test_plantnet_results_carry_the_required_credit():
    """Pl@ntNet の無料枠は recognition API の明示を求めている。"""
    script = client.get("/assets/index.js").text
    assert "Pl@ntNet recognition API" in script
    assert "plantnetCreditHtml(data)" in script
    assert "if(!data.plantnet_used)return" in script  # 使ったときだけ出す
    assert ".source-credit{" in client.get("/assets/index.css").text


def test_privacy_policy_discloses_free_tier_training_use():
    """無料枠は送信内容が学習に使われうる。設定画面だけでなく法的文書にも書く。"""
    privacy = client.get("/privacy").text
    assert "製品改善や機械学習に利用" in privacy
    assert "担当者が内容を確認する場合があります" in privacy
    assert "Pl@ntNet は送信された写真をデータベースへ保存せず" in privacy


def test_providers_are_ordered_by_what_costs_nothing_first():
    """Ollama は無料、Gemini は無料枠あり、残りは従量課金。試せる順に並べる。"""
    assert list(main.config_store.MODELS) == ["local", "gemini", "openai", "anthropic"]
    assert list(main.config_store.DEFAULT_MODELS) == ["local", "gemini", "openai", "anthropic"]
    page = client.get("/settings").text
    assert re.findall(r'name="provider" value="([a-z]+)"', page) == ["local", "gemini", "openai", "anthropic"]
    # 並べ替えでマークアップを壊していないこと
    assert page.count('<label class="provider') == 4
    assert page.count("<label") == page.count("</label>")
    assert page.count("<span") == page.count("</span>")
    for control in ["model-local", "model-gemini", "model-openai", "model-anthropic",
                    "key-gemini", "key-openai", "key-anthropic", "local-llm-url"]:
        assert f'id="{control}"' in page, control


def test_saving_still_works_after_reordering(tmp_path):
    payload = {"provider": "gemini", "models": {"gemini": "gemini-3.6-flash"},
               "local_llm": {"url": "http://127.0.0.1:11434"},
               "api_keys": {"gemini": "test-key"}, "delete_keys": [], "affiliate": {}}
    saved = client.post("/api/settings", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["provider"] == "gemini"
    assert saved.json()["api_key_configured"]["gemini"] is True


def test_wikipedia_rule_lives_in_one_place():
    """言語の出し分けを画面ごとに書くと、片方だけ直してずれる。"""
    shared = client.get("/assets/species-links.js").text
    assert "function wikipediaUrl(candidate)" in shared
    assert '"https://" + (japanese ? "ja" : "en") + ".wikipedia.org/w/index.php?search="' in shared
    # 記事の有無を問い合わせず検索URLにする（無ければ検索結果が出るので壊れない）
    assert 'if (!term) return ""' in shared
    # 旧値の互換もここ1か所で持つ
    assert 'name === "日本語名なし" || name === "和名未登録"' in shared
    for page, script in [("/", "/assets/index.js"), ("/history", "/assets/history.js")]:
        html = client.get(page).text
        assert '<script src="/assets/species-links.js" defer></script>' in html, page
        # 共通ファイルを先に読む（defer は記述順に走る）
        assert html.index("species-links.js") < html.index(script), page
        body = client.get(script).text
        assert "function wikipediaUrl" not in body, script  # 各画面で再定義しない
        assert "function noJapaneseName" not in body, script


def test_both_screens_offer_the_wikipedia_link():
    for script in ["/assets/index.js", "/assets/history.js"]:
        body = client.get(script).text
        assert ">Wikipedia ↗</a>" in body, script
        assert "wikipediaUrl(c)" in body, script
        link = body[body.index("wikipediaUrl(c)"):body.index(">Wikipedia ↗")]
        assert 'target="_blank"' in link and 'rel="noopener noreferrer"' in link, script
    assert ".candidate .links a{" in client.get("/assets/history.css").text


def test_old_records_are_shown_with_the_current_wording():
    """端末内の記録には旧値が残る。読む人には、いまの表記で見せる。"""
    shared = client.get("/assets/species-links.js").text
    assert "function commonNameLabel(candidate)" in shared
    assert 'if (noJapaneseName(candidate?.common_name_ja)) return "日本語名なし"' in shared
    history = client.get("/assets/history.js").text
    assert "esc(commonNameLabel(c))" in history
    assert 'esc(c.common_name_ja||"候補")' not in history  # 旧値をそのまま出さない


def test_pages_and_assets_are_revalidated_not_guessed():
    """Cache-Control が無いと、ブラウザが Last-Modified から新鮮期間を推測して
    再検証せずに古い CSS/JS を使う。HTML が古いと新しい <script> タグごと消える。"""
    for path in ["/", "/settings", "/history", "/privacy", "/terms",
                 "/assets/index.js", "/assets/species-links.js", "/assets/index.css", "/theme.js"]:
        assert client.get(path).headers.get("cache-control") == "no-cache", path
    # 同梱ライブラリはバージョン固定なので長期キャッシュしてよい
    vendor = client.get("/vendor/leaflet/leaflet.js").headers.get("cache-control")
    assert "immutable" in vendor and "max-age=31536000" in vendor


def test_assets_still_answer_304_so_no_cache_stays_cheap():
    first = client.get("/assets/species-links.js")
    etag = first.headers["etag"]
    again = client.get("/assets/species-links.js", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_record_links_do_not_depend_on_the_later_enrich_pass():
    """記録は簡易表示を先に出し、あとから詳細へ差し替える。差し替えが失敗しても
    リンクが消えないよう、最初の描画にも入れておく。"""
    history = client.get("/assets/history.js").text
    simple = history[history.index("(e.candidates||[]).map"):]
    simple = simple[:simple.index('.join("")')]
    assert "candidateLinks(c)" in simple
    # 失敗を握りつぶさない（簡易表示のまま残ることに気づけるように）
    assert "enrich().catch(()=>{})" not in history
    assert "記録の詳細を組み立てられませんでした" in history


def test_records_show_everything_they_store():
    """保存しているのに見せていない項目があった。記録から辿れるようにする。"""
    history = client.get("/assets/history.js").text
    # 撮影画面と同じ参照先
    for link in ["sourceUrl(name)", "wikipediaUrl(c)", "c.taxonomy_url", "animalReference(c,category)"]:
        assert link in history, link
    # 保存済みだが未表示だったもの
    assert "taxonomyBadge(c)" in history and "図鑑にある名前です" in history
    assert "証拠の強さ" in history          # evidence_strength
    assert "分類：" in history               # category
    assert "まちがい防止" in history         # resultMeta.strictMode
    assert "Pl@ntNet recognition API" in history  # plantnetUsed のときの帰属
    assert "confidenceMeter(c)" in history
    # 幅は style 属性ではなく CSSOM (CSP: style-src 'self')
    assert "bar.style.width=bar.dataset.width" in history
    assert 'style="width:' not in history


def test_link_builders_are_shared_by_both_screens():
    shared = client.get("/assets/species-links.js").text
    assert "function sourceUrl(name)" in shared
    assert "function animalReference(candidate, category)" in shared
    for script in ["/assets/index.js", "/assets/history.js"]:
        body = client.get(script).text
        assert "function sourceUrl" not in body, script
        assert "function animalReference(" not in body, script


APP_NAME = "生きものノート"


def test_every_page_carries_the_app_name():
    for path, title in [("/", APP_NAME), ("/settings", f"設定 · {APP_NAME}"),
                        ("/history", f"調べた記録 · {APP_NAME}"),
                        ("/privacy", f"プライバシーポリシー · {APP_NAME}"),
                        ("/terms", f"利用規約 · {APP_NAME}")]:
        page = client.get(path).text
        assert f"<title>{title}</title>" in page, path
        assert "Species Explorer" not in page, path
    # 法務文書と広告開示は正式名称で書く
    assert f"本ポリシーは、{APP_NAME}（以下「本サービス」）" in client.get("/privacy").text
    assert f"運営者：{APP_NAME} 運営者" in client.get("/terms").text
    assert f"Amazonのアソシエイトとして、{APP_NAME}は適格販売" in client.get("/").text


def test_internal_identifiers_are_left_alone():
    """表示名だけを変える。記録の保存先まで変えると既存の記録が読めなくなる。"""
    index = client.get("/assets/index.js").text
    assert 'indexedDB.open("species-history",1)' in index
    assert "species-public-settings" in index
    assert "species-key-" in client.get("/assets/species-links.js").text
    assert "species-theme" in client.get("/theme.js").text
    for path in ["/assets/index.js", "/assets/history.js", "/assets/settings.js"]:
        assert client.get(path).status_code == 200


def test_app_name_never_breaks_across_lines():
    """日本語の見出しは任意の位置で折れる。名前が2行に割れると読めない。"""
    css = client.get("/assets/index.css").text
    assert "white-space:nowrap" in css[css.index("h1{"):css.index("h1{") + 200]
    # 狭い画面でも収まるよう下限を下げてある
    assert "clamp(20px,3vw,30px)" in css


def test_subtitle_states_one_thing():
    """副題は機能の説明だけ。全年齢向けであることは規約と結果下の注意書きが担う。"""
    page = client.get("/").text
    assert '<div class="subtitle">写真から植物・動物の名前を調べる</div>' in page
    assert "どなたでも使えます" not in page
    assert ".subtitle span" not in client.get("/assets/index.css").text


def test_record_ads_are_loaded_only_when_a_record_is_opened():
    """一覧を出すだけで全記録ぶんの商品APIを呼ばない。50件×候補3で150回になる。"""
    history = client.get("/assets/history.js").text
    assert 'detail.addEventListener("toggle",load)' in history
    assert "if(shell.dataset.loaded)return" in history      # 開き直しで再取得しない
    assert "if(detail.open)loadProducts(record,shell)" in history


def test_record_ads_show_several_products_with_pictures():
    history = client.get("/assets/history.js").text
    assert "function productCard(p)" in history
    assert 'class="product-image"' in history and 'class="product-grid"' in history
    assert 'rel="sponsored noopener noreferrer"' in history
    assert '広告 · ' in history                              # 広告と明示する
    css = client.get("/assets/history.css").text
    assert ".product-grid{" in css and ".product-card{" in css


def test_record_ads_prefer_the_species_over_generic_field_guides():
    """「分類+図鑑」は必ずヒットするので、先に置くとどの記録でも同じ図鑑が並ぶ。"""
    history = client.get("/assets/history.js").text
    assert "function productQueries(record)" in history
    assert "shuffle(specific).slice(0,3)" in history        # 種名の切り口を先に、順はランダム
    assert 'specific.push({q:name,index:"Books"})' in history   # その種を扱った本
    assert '{q:category+" 図鑑",index:"Books",generic:true}' in history
    # 一般書は枠を埋める保険。多くても2件までにして種固有の品を押しのけない
    assert 'shuffle(found.generic).slice(0,2)' in history
    assert "product-fallback" in history                    # 全滅なら検索リンクへ


def test_record_ads_keep_food_away_from_the_safety_warning():
    """「食べられるかは判定しません」の隣に食品を並べない。誤同定のとき危険な後押しになる。"""
    history = client.get("/assets/history.js").text
    assert "function looksEdible(title)" in history
    assert "EDIBLE_WORDS" in history
    for word in ["茶", "食用", "乾燥", "サプリ", "おやつ"]:
        assert f'"{word}"' in history, word
    assert "looksEdible(product.title)" in history
    # 種名だけで引くと食品が上位に来るため、用途を添える
    assert 'specific.push({q:name,index:"All"})' not in history
    assert 'name+" 観察"' in history


def test_record_ads_drop_duplicates_by_title_too():
    """同じ品が別URLで返ることがある。"""
    history = client.get("/assets/history.js").text
    assert "seen.has(product.url)||seen.has(key)" in history


def test_product_images_are_allowed_by_the_policy():
    policy = client.get("/history").headers["content-security-policy"]
    assert "https://*.media-amazon.com" in policy


def test_records_can_be_examined_again():
    """元の写真は残っていないので、保存済みの縮小画像を送り直す。"""
    history = client.get("/assets/history.js").text
    assert "async function reidentify(record,button,message)" in history
    assert 'fd.append("files",record.thumbnail,"photo.jpg")' in history
    assert 'e.thumbnail?\'<button class="btn again"' in history   # 写真が無い記録には出さない
    assert "調べ直しています…" in history
    # 公開版は BYOK。撮影画面と同じ形でキーとモデルを渡す
    for field in ["request_provider", "request_model", "request_api_key", "request_plantnet_key"]:
        assert field in history, field
    # 元の記録は消さず、新しい記録として足す（前後を見くらべられる）
    assert "async function saveRerun(source,data)" in history
    assert "rerunOf:source.id" in history
    assert "thumbnail:source.thumbnail" in history
    assert "coordinates:source.coordinates" in history
    assert ".slice(50)" in history   # 上限50件は撮影画面と同じ


def test_adverts_follow_the_first_candidate():
    """候補を巡回させると、確からしさの低い2番目3番目で商品を引く。
    どの候補の広告なのかも読み手に分からない。"""
    index = client.get("/assets/index.js").text
    assert "function topCandidateAffiliateLink(candidates,category)" in index
    assert "affiliateCursor" not in index
    assert "candidates[0]" in index
    history = client.get("/assets/history.js").text
    assert "const top=(record.candidates||[])[0]" in history
    assert "Math.floor(Math.random()*named.length)" not in history  # ランダム選択をやめた
    # フォールバックも第一候補から取る（window.name を拾わない）
    assert "const topCandidate=(record.candidates||[])[0]" in history


def test_backup_carries_photos_without_tripping_the_policy():
    """data: URL への fetch は connect-src 'self' に弾かれる。自前でデコードする。"""
    backup = client.get("/assets/backup.js").text
    assert "readAsDataURL" in backup                 # 写真を1ファイルへ収める
    assert "fetch(value)" not in backup              # CSP に触れる書き方をしない
    assert "atob(value.slice(comma + 1))" in backup
    policy = client.get("/settings").headers["content-security-policy"]
    assert "connect-src 'self'" in policy            # 緩めていないこと


def test_restore_does_not_wipe_what_is_already_there():
    backup = client.get("/assets/backup.js").text
    assert ".clear()" not in backup                  # 既存の記録を消さない
    assert 'transaction.objectStore("entries").put(entry)' in backup
    assert 'payload.format !== BACKUP_FORMAT' in backup   # 別物を読ませない


def test_records_are_written_back_whenever_they_change():
    backup = client.get("/assets/backup.js").text
    assert "function scheduleAutoBackup()" in backup
    assert "clearTimeout(backupTimer)" in backup               # まとめて1回だけ書く
    # 記録が変わる箇所すべてから呼ぶ
    assert "scheduleAutoBackup()" in client.get("/assets/index.js").text
    history = client.get("/assets/history.js").text
    assert history.count("scheduleAutoBackup()") >= 2          # 削除と再判定
    for page in ["/", "/history", "/settings"]:
        assert '<script src="/assets/backup.js" defer></script>' in client.get(page).text, page


def test_every_script_actually_parses():
    """文字列検査だけでは構文エラーを見逃す。実際に壊れた JS を配って
    撮影画面が動かなくなったことがあるため、パースまで確かめる。"""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無いため構文チェックを省略")
    root = Path(__file__).parents[1] / "static"
    scripts = sorted(root.glob("assets/*.js")) + [root / "theme.js"]
    assert len(scripts) >= 5
    for script in scripts:
        result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {result.stderr[:300]}"


def test_pages_load_every_script_they_depend_on():
    """settings.html が species-links.js を読み忘れ、APIキーを保存できていなかった。
    参照している関数が、そのページで読まれる範囲に定義されているか確かめる。"""
    provided = {}
    for name in ["species-links.js", "backup.js", "gdrive.js", "index.js", "history.js", "settings.js"]:
        body = client.get(f"/assets/{name}").text
        provided[name] = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", body))
    provided["theme.js"] = set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", client.get("/theme.js").text))

    shared = ["readApiKey", "writeApiKey", "clearApiKey", "keepingKeys", "displayName",
              "wikipediaUrl", "providerLabel", "scheduleAutoBackup",
              # ドライブへの保存。gdrive.js を設定画面にしか読ませておらず、写真を調べても
              # 記録が書かれないまま黙っていた
              "autoSaveToDrive", "ensureDriveToken", "saveToDrive", "loadFromDrive",
              "driveSignedIn", "driveLinked", "driveConfigured", "forgetDrive", "buildBackup"]
    for path in ["/", "/history", "/settings"]:
        html = client.get(path).text
        loaded = [name for name in re.findall(r'src="/assets/([a-z-]+\.js)"', html) if name in provided]
        available = set().union(*[provided[name] for name in loaded])
        # そのページで読まれる全てのスクリプトを見る。呼ぶ側が共通ファイルのこともある
        for name in loaded:
            body = client.get(f"/assets/{name}").text
            for func in shared:
                if re.search(rf"\b{func}\s*\(", body):
                    assert func in available, f"{path}: {name} が {func} を呼ぶが、定義が読み込まれていない"


def test_google_drive_talks_to_google_directly():
    """Drive は WebDAV を提供しないので OAuth と Drive API を使う。通信はブラウザから
    Google へ直接行き、サーバーを経由しない（写真もトークンも運営者を通らない）。"""
    drive = client.get("/assets/gdrive.js").text
    assert "https://www.googleapis.com/auth/drive.file" in drive   # 自分が作ったファイルだけ
    assert "auth/drive'" not in drive and '"drive"' not in drive    # 全体アクセスは求めない
    assert "/api/storage/" not in drive                             # 中継しない
    assert "let driveToken = null" in drive
    assert "localStorage.setItem(DRIVE_KEY" not in drive.split("function rememberDriveFile")[0]
    # トークンは保存しない（盗まれたときの被害を残さない）
    assert "localStorage" not in drive.split("let driveToken")[1].split("function driveFileId")[0]


def test_google_script_is_loaded_only_when_used():
    drive = client.get("/assets/gdrive.js").text
    assert "function loadGoogleIdentity()" in drive
    assert 'script.src = "https://accounts.google.com/gsi/client"' in drive
    page = client.get("/settings").text
    assert "accounts.google.com" not in page      # 最初から読み込まない


def test_policy_allows_google_but_nothing_arbitrary():
    policy = client.get("/settings").headers["content-security-policy"]
    assert "script-src 'self' https://accounts.google.com" in policy
    assert "https://www.googleapis.com" in policy
    assert "frame-src https://accounts.google.com" in policy
    # 任意ホストを開けたわけではない
    assert "*" not in policy.split("connect-src")[1].split(";")[0]
    assert "'unsafe-inline'" not in policy


def test_drive_says_so_when_the_operator_has_not_set_it_up():
    settings = client.get("/api/settings").json()
    assert "google_client_id" in settings          # 公開情報。秘密鍵は使わない
    script = client.get("/assets/settings.js").text
    assert "IKIMONO_GOOGLE_CLIENT_ID" in script    # 何をすれば使えるか伝える


def test_sessions_cannot_be_forged():
    """署名付きクッキーなので、中身を書き換えたら通らない。"""
    import auth
    user = {"subject": "sub-1", "email": "a@example.com"}
    cookie = auth.session_for(user)
    assert auth.read_session(cookie)["sub"] == "sub-1"
    body, _, signature = cookie.partition(".")
    assert auth.read_session(body + ".x" + signature[1:]) is None       # 署名を差し替える
    forged = auth.sign_session({"sub": "someone-else", "exp": 9999999999})
    assert auth.read_session(forged.split(".")[0] + "." + signature) is None
    # 期限切れは通さない
    assert auth.read_session(auth.sign_session({"sub": "sub-1", "exp": 1})) is None
    assert auth.read_session(None) is None and auth.read_session("garbage") is None


def test_id_token_must_match_this_app():
    """Google から直に受け取る応答でも、宛先と nonce は確かめる。"""
    import auth, base64, json, time

    def token(**claims):
        body = {"iss": "https://accounts.google.com", "aud": auth.CLIENT_ID or "cid",
                "nonce": "n1", "exp": time.time() + 600, "email": "a@example.com", "sub": "s1"}
        body.update(claims)
        raw = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip("=")
        return "x." + raw + ".y"

    original = auth.CLIENT_ID
    auth.CLIENT_ID = "cid"
    try:
        assert auth._claims_from_id_token(token(), "n1")["sub"] == "s1"
        for bad, why in [({"aud": "another-app"}, "別アプリ宛"), ({"nonce": "n2"}, "nonce 不一致"),
                         ({"iss": "https://evil.example"}, "発行者違い"), ({"exp": 1}, "期限切れ"),
                         ({"email": ""}, "メールなし")]:
            try:
                auth._claims_from_id_token(token(**bad), "n1")
                raise AssertionError(f"{why} を通してしまった")
            except auth.AuthError:
                pass
    finally:
        auth.CLIENT_ID = original


def test_login_is_not_demanded_before_it_is_configured():
    """設定を入れる前に必須にすると、運営者も含めて誰も入れなくなる。"""
    source = (Path(__file__).parents[1] / "main.py").read_text()
    assert "if (not PUBLIC_MODE or not auth.configured()" in source
    # 読んでから決めるための文書と、画面の部品は開けておく
    for path in ["/login", "/privacy", "/terms", "/api/me"]:
        assert f'"{path}"' in source.split("OPEN_PATHS")[1].split("\n\n")[0], path
    assert '"/assets/"' in source.split("OPEN_PREFIXES")[1].split("\n")[0]


def test_the_server_stores_only_an_identifier_and_an_email():
    """ログインしても預かるものが増えないことを、表の定義で確かめる。"""
    source = (Path(__file__).parents[1] / "auth.py").read_text()
    columns = source.split("CREATE TABLE IF NOT EXISTS users (")[1].split(")\"\"\"")[0]
    for allowed in ["subject", "email", "created_at", "last_seen_at", "plan"]:
        assert allowed in columns, allowed
    for never in ["photo", "image", "api_key", "record", "history", "password", "token"]:
        assert never not in columns.lower(), never
    # パスワードを持たない以上、ハッシュ処理も要らない
    assert "bcrypt" not in source and "password" not in source.lower().replace("passwords are not", "")
    assert "def delete_user" in source          # 退会できる


def test_login_page_states_what_is_kept():
    page = client.get("/login").text
    assert "パスワードは本サービスでは預かりません" in page
    assert "アカウントの識別子とメールアドレスだけ" in page
    assert "/privacy" in page and "/terms" in page


def test_privacy_matches_what_we_actually_keep():
    """書いていないものを取らない。ログインを入れた以上、記載も直す。"""
    page = client.get("/privacy").text
    assert "利用者登録を求めず" not in page          # ログイン必須にしたので、この約束は撤回した
    assert "メールアドレスと、Googleが発行する識別子" in page
    assert "パスワードは受け取らず、保存もしません" in page
    assert "退会する" in page                        # 消せることを書く
    assert "保護者の方の同意" in page                # 全年齢向けなので必要


def test_records_go_to_drive_and_nowhere_else():
    """保存先はひとつ。ログインに Google アカウントを使う以上、全員が持っている
    置き場はドライブで、選ばせる理由がない。"""
    page = client.get("/settings").text
    assert "記録の保存" in page and 'id="drive-connect"' in page
    for gone in ["storage-kind", "cloud-service", "cloud-connect", "choose-target",
                 "export-backup", "import-backup"]:
        assert gone not in page, gone


def test_the_relay_is_gone():
    """中継は SSRF の入口だった。使わなくなったので、口ごと閉じる。"""
    assert not (Path(__file__).parents[1] / "webdav_relay.py").exists()
    source = (Path(__file__).parents[1] / "main.py").read_text()
    assert "webdav_relay" not in source and "/api/storage/" not in source
    for path in ["/api/storage/put", "/api/storage/get", "/api/storage/list"]:
        assert client.post(path, json={"url": "https://example.com/"}).status_code == 404, path


def test_records_are_written_back_without_asking_every_time():
    """記録するたび許可を求められては使い物にならない。二度目からは黙って取り直す。"""
    drive = client.get("/assets/gdrive.js").text
    assert "async function ensureDriveToken(clientId)" in drive
    assert 'requestAccessToken(silent ? {prompt: "none"} : {prompt: "consent"})' in drive
    assert "async function autoSaveToDrive()" in drive
    # 取れなければ黙って諦める。記録は端末の中に残る
    body = drive.split("async function ensureDriveToken(clientId) {")[1].split("\n}")[0]
    assert body.count("return null;") == 2      # つないでいないとき、取れなかったとき
    backup = client.get("/assets/backup.js").text
    assert "if (typeof autoSaveToDrive === \"function\") autoSaveToDrive();" in backup
    # トークンは保存しない。覚えるのは「一度つないだ」という事実だけ
    assert "species-drive-linked" in drive
    assert "localStorage" not in drive.split("let driveToken")[1].split("const DRIVE_LINKED")[0]


def test_settings_page_touches_only_elements_that_exist():
    """要素が消えたのに参照が残ると、load() が途中で止まって画面が育たない。
    実際に運営者用の設定画面が、モデルの選択肢を描かないまま出ていた。"""
    html = (Path(__file__).parents[1] / "static" / "settings.html").read_text()
    script = (Path(__file__).parents[1] / "static" / "assets" / "settings.js").read_text()
    ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'\$\("([^"]+)"\)', script))
    # 無い要素に触るなら、必ず存在を確かめてから
    for name in sorted(used - ids):
        guarded = re.search(rf'const \w+=\$\("{re.escape(name)}"\);\s*\n\s*if\(\w+\)', script)
        assert guarded, f'{name} は settings.html に無く、存在確認もしていない'


def test_every_page_that_records_can_also_save_them():
    """記録を書き換えるページは、保存する手段も持っていなければならない。
    gdrive.js を設定画面にしか読ませておらず、写真を調べても記録が
    ドライブに書かれないまま黙っていた。"""
    for path in ["/", "/history", "/settings"]:
        html = client.get(path).text
        if "scheduleAutoBackup" in client.get("/assets/backup.js").text and "backup.js" in html:
            assert "gdrive.js" in html, f"{path}: 保存の呼び出しはあるが gdrive.js が無い"


def test_a_failed_save_is_not_kept_quiet():
    """黙って失敗し続けると、記録が残っていると思い込んだまま端末を変えて、
    全部消えたことに後で気づく。"""
    drive = client.get("/assets/gdrive.js").text
    assert "function noteDriveStatus(ok, detail)" in drive
    assert "noteDriveStatus(false," in drive and "noteDriveStatus(true," in drive
    history = client.get("/assets/history.js").text
    assert "showSaveState" in history
    assert "Google ドライブへ保存できていません" in history
    assert "記録はこの端末の中だけにあります" in history      # 一度もつないでいない場合
    assert 'id="saveState"' in client.get("/history").text


def test_user_records_survive_a_stateless_host():
    """Cloud Run はリクエストごとにインスタンスが入れ替わる。ファイルに書いても
    次の呼び出しでは消えており、いつから使っている人か分からなくなる。"""
    source = (Path(__file__).parents[1] / "auth.py").read_text()
    assert "def using_firestore()" in source
    for entry in ["def upsert_user", "def find_user", "def delete_user"]:
        body = source.split(entry)[1].split("\ndef ")[0]
        assert "using_firestore()" in body, f"{entry} が置き場を見ていない"
    # 鍵ファイルを置かない。Cloud Run の中ではメタデータサーバーが貸してくれる
    assert "metadata.google.internal" in source
    assert "service_account.json" not in source and "GOOGLE_APPLICATION_CREDENTIALS" not in source


def test_the_container_carries_only_what_it_needs():
    """ホーム全体の pyproject.toml には無関係な依存が106個ある。持ち込まない。"""
    root = Path(__file__).parents[1]
    # コメントに書いた「streamlit など」に反応しないよう、実際の行だけを見る
    lines = [line.split("#")[0].strip() for line in (root / "requirements.txt").read_text().splitlines()]
    packages = {re.split(r"[=<>~\[]", line)[0] for line in lines if line}
    assert packages == {"fastapi", "uvicorn", "httpx", "pillow", "python-multipart"}, packages
    dockerfile = (root / "Dockerfile").read_text()
    assert "${PORT}" in dockerfile          # Cloud Run が渡すポートに従う
    assert "USER app" in dockerfile         # root で動かさない
    assert "IKIMONO_PUBLIC_MODE=1" in dockerfile
    ignored = (root / ".dockerignore").read_text()
    assert "tests/" in ignored and "eval/" in ignored


def test_connecting_writes_something_right_away():
    """自動保存は記録が増減したときに動く。つないだだけでは何も現れず、
    ドライブを見に行った利用者は失敗したと思う。"""
    script = client.get("/assets/settings.js").text
    connect = script.split('$("drive-connect").onclick')[1].split("};")[0]
    assert "await saveToDrive()" in connect, "つないだ直後に書いていない"


def test_popups_can_talk_back_to_us():
    """COOP を same-origin にすると、開いたポップアップとの window.opener が切れる。
    Google の認可はポップアップで許可を取り、親へ postMessage で結果を返すので、
    認可が通っているのに結果が届かず「ポップアップが閉じられた」ようにしか見えない。
    設定側をいくら直しても症状が変わらず、原因の特定に時間を要した。"""
    policy = client.get("/settings").headers["cross-origin-opener-policy"]
    assert policy == "same-origin-allow-popups"
    # unsafe-none まで緩めない。別サイトから開かれたときの保護は残す
    assert policy != "unsafe-none"


def test_the_reason_a_popup_failed_is_shown():
    """「つなげませんでした」だけでは、こちらの設定なのか相手の設定なのか分からない。"""
    drive = client.get("/assets/gdrive.js").text
    assert 'const kind = error?.type || "unknown"' in drive
    assert "popup_failed_to_open" in drive and "popup_closed" in drive


def test_api_keys_are_left_out_unless_asked_for():
    """既定では持ち出さない。ファイルが漏れたとき、そのまま課金されるキーが渡る。
    ただし端末や入口 (公開版と :8443) を移るたびに入れ直すのは重いので、
    承知のうえで一緒に置くことも選べる。"""
    backup = client.get("/assets/backup.js").text
    assert "function savingKeys()" in backup
    assert 'localStorage.getItem(SAVE_KEYS_FLAG) === "1"' in backup   # 既定は false
    assert "if (savingKeys()) {" in backup                            # 選んだときだけ入れる
    page = client.get("/settings").text
    assert 'id="save-keys"' in page
    assert "料金が発生する恐れがあります" in page       # 何が起きるか書く
    assert "共用の端末" in page
    # 選ばせる以上、既定で入っていてはいけない
    assert 'id="save-keys" type="checkbox"><span>' in page.replace('<input ', '')


def test_privacy_says_where_keys_can_go():
    page = client.get("/privacy").text
    assert "APIキーも一緒に保存する" in page
    assert "既定では保存しません" in page
    assert "ブラウザから Google へ直接" in page


def test_settings_page_reads_top_to_bottom():
    """順に読んで、順に決められる並びにする。以前は保存ボタンの後ろに設定項目があり、
    誰でログインしているかは画面の真ん中にあった。"""
    page = client.get("/settings").text
    order = [page.index(marker) for marker in [
        'id="account-section"',      # 誰で入っているか
        'id="settingsForm"',         # 使うAI
        'id="keep-keys"',            # キーの残し方 (保存より前)
        'id="settings-save"' if 'id="settings-save"' in page else 'この端末に保存',
        'aria-labelledby="backup-heading"',   # 記録の保存
    ]]
    assert order == sorted(order), "設定画面の並びが前後している"


def test_only_the_chosen_provider_is_unfolded():
    """3つ全部を開いておくと、設定画面の6割が、選ばないものの入力欄で埋まる。"""
    css = client.get("/assets/settings.css").text
    assert ".provider:not(:has(input:checked)) .fields" in css
    assert ".provider:not(:has(input:checked)) .setup-guide" in css
    # 選んだときは元の見た目に戻したいので、隠す側にだけ指定する
    assert ".provider:has(input:checked)>*{display:block}" not in css


def test_the_warning_does_not_greet_you_first():
    """最初に目に入るのが長い警告では、使う前に気持ちが萎える。中身は残して畳む。"""
    page = client.get("/settings").text
    assert 'class="panel stacked guardian-note"' in page      # details で畳んである
    assert "料金とお子さまの利用について" in page
    assert "契約者ご本人" in page                              # 中身は消していない


def test_empty_areas_do_not_hold_space():
    """写真を選ぶ前の 02 と 03 が、空のまま340pxほど占めていた。
    案内の一行が読めれば足りる。"""
    css = client.get("/assets/index.css").text
    heights = re.findall(r"\.placeholder\{[^}]*min-height:(\d+)px", css)
    assert heights, "placeholder の高さ指定が見つからない"
    for value in heights:
        assert int(value) <= 100, f"空欄が {value}px を占めている"


def test_the_long_notes_are_folded_but_kept():
    """大事だが、設定を触るたびに読むものではない。畳んでも中身は消さない。"""
    page = client.get("/settings").text
    security = page.split('aria-labelledby="security-heading"')[1].split("</section>")[0]
    assert "<details" in security, "保存と安全性が畳まれていない"
    assert security.count("<li>") >= 5, "中身が減っている"


def test_the_browser_can_keep_the_keys_for_us():
    """autocomplete="new-password" は「新しいパスワードの入力欄」の宣言で、
    ブラウザは保存を提案しない。端末を移るたびに入れ直すことになっていた。"""
    page = client.get("/settings").text
    # Amazon の認証情報は運営者専用で、利用者は触らない。ここでは対象外
    for name in ["gemini", "openai", "anthropic", "plantnet"]:
        assert f'id="key-{name}" name=' in page and f'autocomplete="new-password" placeholder' not in \
            page.split(f'id="key-{name}"')[1][:120], name
        assert f'name="ikimono-{name}-key" type="password" autocomplete="current-password"' in page, name
        # どのサービスの鍵かを示さないと、ブラウザが4つを区別できない
        assert f'value="{name}" autocomplete="username"' in page, name
    assert "パスワードを保存しますか" in page      # 知らなければ、提案が出ても意味が分からない
    assert "本サービスは受け取りません" in page
