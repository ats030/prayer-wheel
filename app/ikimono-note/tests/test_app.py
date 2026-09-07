import importlib
import json
import os
import re
import time
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
    assert "candidate.uncertainty" in source
    assert "candidate.evidence_gaps" in source
    assert ".slice(0,5)" in source


def test_shooting_guide_offers_camera_and_library_without_losing_photos():
    """「もっと確かめたいこと」を読んだその場から、撮り足せること。

    案内の追加ボタンは、いま選んでいる写真を置き換えず足す。置き換えると
    最初の全体像が消え、確かめたい寄りの1枚だけで調べ直すことになる。
    """
    source = page_source("/")
    assert 'id="addPhotoCamera"' in source
    assert 'id="addPhotoLibrary"' in source
    assert 'id="libraryAdd"' in source
    # 足す側は addFiles、選びなおす側だけが setFiles
    assert '$("libraryAdd").onchange=e=>{addFiles(e.target.files)' in source
    assert '$("camera").onchange=e=>{addFiles(e.target.files)' in source
    assert '$("library").onchange=e=>{setFiles(e.target.files)' in source
    assert "selected=[...selected,...added]" in source
    assert "const MAX_PHOTOS=3" in source
    assert 'class="btn preview-remove"' in source
    assert "function removeSelectedPhoto(index)" in source
    assert "selected.splice(index,1)" in source
    assert "調べる写真は1枚以上必要です。" in source


def test_shooting_guide_appears_whenever_something_is_left_to_check():
    """決め手のある候補でも、確かめたいことが残っていれば案内を出すこと。"""
    source = page_source("/")
    assert "if(!points.length&&candidates.length&&!candidates.some(weak))return \"\"" in source


def test_index_saves_history_but_does_not_render_it():
    """記録の作成はトップが担い、閲覧は /history だけが担う。"""
    response = client.get("/")
    source = page_source("/")
    assert 'href="/settings"' in source
    assert 'href="/history"' in source
    assert 'indexedDB.open("species-history",1)' in source
    assert 'slice(50)' in source
    assert 'gps.latitude.toFixed(4)' in source
    assert 'Math.min(1,edge/Math.max(bitmap.width,bitmap.height))' in source
    assert 'model:data.model||""' in source
    assert 'resultMeta:{strictMode:' in source
    # 表示専用の重複実装を持たないこと（隠れたまま到達できない実装を再び作らない）
    for gone in ["historyPanel", "historyToggle", "renderHistoryList", "historyLightbox",
                 "historyCandidateHtml", "historyAffiliateLink", "historyMessage"]:
        assert gone not in source, gone
    # 保存に失敗したら、隠れた要素ではなく利用者が見ている場所へ出す
    # 書き込みの失敗は、識別と同じ status 行に出す (隠れた場所へ落とさない)
    assert 'saveHistory(data,{...pending,photos:historyPhotos})' in source
    assert 'この端末の記録には保存できませんでした。' in source
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
    assert 'id="clear"' not in page   # まとめて消すボタンは置かない
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
    assert 'OpenStreetMap contributors' in page_source("/dashboard")


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
    assert "affiliateProductLink(c,data.category)" in page_source("/")
    assert "loadAmazonProducts()" in page_source("/")
    assert "position:fixed" not in page_source("/")
    assert "position:sticky" not in page_source("/")
    assert 'id="reset-affiliate-visibility"' not in response.text
    index = page_source("/")
    assert 'id="gpsButton"' not in index
    assert "requestCurrentLocation" not in index
    assert 'source:"current"' not in index
    assert "navigator.geolocation" not in index
    assert '写真に位置情報が残っていれば' in index
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
                    "partner_tag": "test-22", "limit": 10, "search_index": "All"}
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


def test_identify_can_run_behind_a_job_so_a_refresh_does_not_lose_it(monkeypatch):
    """画面を更新しても続きから受け取れること。

    ブラウザが待っているあいだだけ生きる作りだと、更新した瞬間に答えが行き場を
    なくす。Ollama では1分ほどかかるので、その1分は画面を触れないことになる。
    """
    monkeypatch.setattr(main.vision, "identify",
                        lambda images, model, **context: {"category": "植物", "summary": "", "candidates": []})
    with TestClient(main.app, base_url="http://localhost") as running_client:
        started = running_client.post("/identify", files=[("files", ("a.jpg", usable_photo(), "image/jpeg"))],
                                      data={"background": "true"})
        assert started.status_code == 202
        job = started.json()["job"]
        assert started.json()["status"] == "running"
        assert job

        for _ in range(80):
            polled = running_client.get(f"/identify/job/{job}")
            assert polled.status_code == 200
            if polled.json()["status"] != "running":
                break
            time.sleep(0.1)
        payload = polled.json()
        assert payload["status"] == "done", payload
        assert payload["result"]["category"] == "植物"
        # 同じ札で二度読める (受け取った直後に閉じてしまっても、開き直せば見られる)
        assert running_client.get(f"/identify/job/{job}").json()["status"] == "done"


def test_a_failed_job_carries_the_reason_not_a_hang(monkeypatch):
    """後ろで落ちたときも札に残す。残さないと画面が待ち続ける。"""
    def boom(*args, **kwargs):
        raise main.vision.VisionError("Ollamaに接続できませんでした")
    monkeypatch.setattr(main.vision, "identify", boom)
    with TestClient(main.app, base_url="http://localhost") as running_client:
        job = running_client.post("/identify", files=[("files", ("a.jpg", usable_photo(), "image/jpeg"))],
                                  data={"background": "true"}).json()["job"]
        for _ in range(80):
            payload = running_client.get(f"/identify/job/{job}").json()
            if payload["status"] != "running":
                break
            time.sleep(0.1)
    assert payload["status"] == "error"
    assert payload["status_code"] == 422
    assert "Ollama" in payload["detail"]


def test_an_unknown_job_is_not_a_silent_wait():
    """期限切れ・再起動・別人。どれでも利用者にできることは同じなので同じ答えにする。"""
    response = client.get("/identify/job/deadbeef")
    assert response.status_code == 404
    assert "もう一度お試しください" in response.json()["detail"]


def test_the_job_store_keeps_results_not_photos():
    """置くのは結果だけ。写真は仕事が走っているあいだしか存在しない。"""
    source = (Path(__file__).parents[1] / "jobs.py").read_text(encoding="utf-8")
    assert "TTL_SECONDS" in source and "MAX_JOBS" in source
    for leaked in ["raw_images", "prepared", "image", "photo"]:
        assert leaked not in source.replace("写真", ""), leaked
    main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert "raw_images.clear()" in main_source     # 終わったら捨てる


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
    assert 'id="ollama-check"' in source
    assert 'id="ollama-check-state"' in source
    settings_js = client.get("/assets/settings.js").text
    assert 'url+"/api/tags"' in settings_js
    assert 'url+"/api/show"' in settings_js
    assert '.includes("vision")' in settings_js
    assert "OLLAMA_HOST、OLLAMA_ORIGINS" in settings_js
    assert 'targetAddressSpace:"local"' in settings_js
    assert "function normalizeOllamaUrl(value)" in settings_js
    assert 'url="http://"+url' in settings_js
    assert "Ollama URLを入力してください" in settings_js
    assert "Ollama URLの形式を確認してください" in settings_js
    assert "ローカルネットワークへのアクセス" in settings_js
    assert "設定済みの別端末用URL" not in source
    assert "192.168.11.13" not in source
    assert "Ollama端末のIPアドレス" in source
    assert 'local_llm:{url:' in source
    assert 'id="active-provider"' in source
    # 任意機能の2つ（Pl@ntNet と広告）。持ち出しのクラウド設定も同じ見た目だが別物
    assert 'id="affiliate-panel"' in source and "Pl@ntNet 植物にくわしいサービス" in source
    assert source.count('<details class="panel') >= 2
    assert 'id="save-button"' in source
    assert 'class="message" id="message" aria-live="polite"' in source
    assert source.count("写真から位置情報などを取り除き") == 1
    assert "この画面にない項目（Ollama" not in source



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
    body = client.get("/api/settings").json()
    # 既定は Gemini。訪問者の多くは Ollama を持っておらず、local を既定にすると
    # 初回が必ず失敗する
    assert body["provider"] == "gemini"
    # サーバーからは手元の一覧を引けない
    assert body["available_models"]["local"] == []
    # ただし選べることは伝える。ブラウザから直接呼べるため
    assert body["local_in_browser"] is True


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
    assert "利用者が指定した同じLAN内のOllama" in privacy.text
    assert "192.168.11.13" not in privacy.text
    assert "Google ドライブへの保存" in privacy.text
    assert "1つのファイルへ書き出せます" not in privacy.text
    assert "Google Cloud Run（東京リージョン）" in privacy.text   # 公開の入口。変わったらここも変える
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
        assert 'href="/changelog"' in page.text


def test_changelog_lists_updates_from_the_launch_day_onward():
    """更新履歴は利用者から見た変化を新しい順に並べる。

    公開前の開発期は利用者にとって存在しない期間なので載せない。起点は
    プライバシーポリシーと利用規約の制定日（＝公開日）に揃える。
    """
    page = client.get("/changelog")
    assert page.status_code == 200
    dates = re.findall(r"<h2>(\d{4})年(\d{1,2})月(\d{1,2})日</h2>", page.text)
    assert len(dates) >= 2
    keys = [tuple(int(part) for part in row) for row in dates]
    assert keys == sorted(keys, reverse=True)      # 新しい順
    assert keys[-1] == (2026, 8, 14)               # 起点は公開日
    assert "生きものノートを公開しました" in page.text
    # 内部の言葉をそのまま出さない。読む相手は利用者
    for jargon in ["commit", "refactor", "リファクタ", "テスト追加", "main.py"]:
        assert jargon not in page.text, jargon


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
    for path in ["/", "/settings", "/history", "/dashboard", "/privacy", "/terms", "/changelog"]:
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
    for path in ["/", "/settings", "/history", "/dashboard", "/privacy", "/terms", "/changelog"]:
        page = page_source(path)
        assert '<script src="/theme.js"></script>' in page, path
        assert 'id="themeToggle"' in page, path
        assert ':root[data-theme="dark"]' in page, path
        assert '@media(prefers-color-scheme:dark){:root:not([data-theme="light"])' in page, path


def test_theme_script_loads_before_the_page_body():
    for path in ["/", "/settings", "/history", "/dashboard", "/privacy", "/terms", "/changelog"]:
        page = page_source(path)
        tag_start = page.index('<script src="/theme.js">')
        assert tag_start < page.index("<body"), path
        assert "<style" not in page[:tag_start], path


def test_dashboard_summarizes_existing_records_without_a_new_data_store():
    page = page_source("/dashboard")
    script = client.get("/assets/dashboard.js").text
    assert 'id="totalCount"' in page
    assert 'id="locatedCount"' in page
    assert 'id="notedCount"' in page
    assert 'id="recentList"' in page
    assert 'id="categoryList"' in page
    assert 'id="rankList"' in page
    assert "観察の内訳" in page
    assert "何を観察したかと、名前をどこまで絞れたか" in page
    assert 'indexedDB.open("species-history",1)' in script
    assert 'function categoryCounts(entries)' in script
    assert 'function rankCounts(entries)' in script
    assert 'function piePath(start,end)' in script
    assert 'function pieChart(items,total,label)' in script
    assert 'class="pie-chart"' in script
    assert 'role="img"' in script
    assert 'class="pie-legend-row"' in script
    assert 'style="' not in script
    assert 'CATEGORY_ORDER=["植物","動物","菌類","不明"]' in script
    assert 'species:"種まで",genus:"属まで",family:"科まで"' in script
    assert '"階級の記録なし"' in script
    assert '"候補なし"' in script
    assert 'function showLoadError(error)' in script
    assert '$("categoryList").innerHTML=html' in script
    assert '$("rankList").innerHTML=html' in script
    assert 'entries.slice(0,5)' in script
    assert 'href="/dashboard"' in page_source("/")
    assert 'href="/dashboard"' in page_source("/history")


def test_dashboard_map_is_never_loaded_without_an_explicit_press():
    """位置を含む地図タイルは、ダッシュボードで押すまで第三者へ要求しない。"""
    page = page_source("/dashboard")
    assert "unpkg.com" not in page
    assert '"/vendor/leaflet/leaflet.js"' in page
    assert '"/vendor/leaflet/leaflet.css"' in page
    assert 'id="showMap"' in page
    assert 'id="locateMe"' in page
    assert "現在地へ移動」を押した場合だけ" in page
    assert "navigator.geolocation.getCurrentPosition" in page
    assert "mapInstance.setView([latitude,longitude]" in page
    assert "現在地の利用が許可されていません" in page
    assert 'id="mapLocationState" aria-live="polite"' in page
    assert '$("showMap").onclick=showMap' in page
    assert "drawMap(mapEntries)" in page
    assert "「地図を表示」を押したときだけ" in page
    assert "全国微地形は防災科学技術研究所から" in page
    assert "土地利用は国土交通省から" in page
    assert '"土地条件"' in page
    assert '"標高・起伏"' in page
    assert '"全国微地形"' in page
    assert '"土地利用"' in page
    assert '"湖沼（水深）"' not in page
    assert "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png" in page
    assert page.count("https://cyberjapandata.gsi.go.jp/xyz/lcm25k_2012/{z}/{x}/{y}.png") == 1
    assert "https://cyberjapandata.gsi.go.jp/xyz/experimental_landformclassification1/" in page
    assert "https://cyberjapandata.gsi.go.jp/xyz/hillshademap/{z}/{x}/{y}.png" in page
    assert "https://www.j-shis.bosai.go.jp/map/wms/sstrct/V4" in page
    assert "Z-V4-JAPAN-AMP-VS400_M250-JCODE" in page
    assert "https://nlftp.mlit.go.jp/ksj/tile/L03-b/L03-b-2016/{z}/{x}/{y}.png" in page
    assert "function wmsLayer(tile,source)" in page and "L.tileLayer.wms" in page
    assert "lakedata" not in page and "/lake1/" not in page
    assert "minNativeZoom:5,maxNativeZoom:18" in page
    assert 'type:"landform"' in page
    assert "Math.min(13,Math.max(5,map.getZoom()))" in page
    assert "minNativeZoom:10,maxNativeZoom:16" in page
    assert "minSelectZoom:10" in page
    assert "minNativeZoom:2,maxNativeZoom:16" in page
    assert "opacity:.5" in page and "opacity:tile.opacity??1" in page
    assert 'background:"地図"' in page
    assert "function mapLayer(source)" in page and "L.layerGroup(tiles)" in page
    assert "function landformLayer(source)" in page and "L.geoJSON(data" in page
    assert 'pane:"landformPane"' in page and 'pane:"landDetailPane"' in page
    assert 'class="map-cursor"' in page and 'id="mapReadout"' in page
    map_style = client.get("/assets/dashboard.css").text
    assert ".map-cursor::before{left:50%" in map_style and "transform:translateX(-50%)" in map_style
    assert ".map-cursor::after{left:-8px;top:50%" in map_style and "transform:translateY(-50%)" in map_style
    assert "function centerReadout(map)" in page
    assert "function mapPopup(record)" in page
    assert "record.listThumbnail||photos[0]||record.thumbnail" in page
    assert "bindPopup(mapPopup(record),{maxWidth:220})" in page
    assert "写真なし" in page
    assert ".map-popup-photo" in map_style
    for value_id in ["mapLandform", "mapElevation", "mapMicroterrain", "mapLandUse", "mapVegetation"]:
        assert f'id="{value_id}"' in page
    assert "meshinfo.geojson" in page
    assert 'code.length>=5' in page
    assert "数値地図25000（土地条件）" in page
    assert "api/map/land-use" in page
    assert "instance.on(\"moveend\",updateReadout)" in page
    assert "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php" in page
    assert 'outtype:"JSON"' in page
    assert 'value.toFixed(1)+" m"' in page
    assert "緯度" not in page.split('id="mapReadout"')[1].split("</dl>")[0]
    assert "経度" not in page.split('id="mapReadout"')[1].split("</dl>")[0]
    assert "source.background?[MAP_LAYERS[source.background]]" in page
    assert "attribution:tile.credit||source.credit" in page
    assert "const minimum=MAP_LAYERS[event.name]?.minSelectZoom" in page
    assert '"地形"' not in page and '"起伏"' not in page and '"土地利用（1982〜83年）"' not in page
    history = page_source("/history")
    assert 'id="showMap"' not in history
    assert 'id="historyMap"' not in history
    for path in ["/vendor/leaflet/leaflet.js", "/vendor/leaflet/leaflet.css",
                 "/vendor/leaflet/images/marker-icon.png", "/vendor/leaflet/LICENSE"]:
        assert client.get(path).status_code == 200, path
    assert "BSD 2-Clause" in client.get("/vendor/leaflet/LICENSE").text


PAGES = ["/", "/settings", "/history", "/dashboard", "/privacy", "/terms", "/changelog"]


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
    # 並びをそのまま書くと、許可先を1つ足すたびに落ちる。何を許していないかを見る
    images = policy.split("img-src")[1].split(";")[0]
    assert "'self'" in images and "blob:" in images
    assert "*" not in images.replace("https://*.media-amazon.com", "").replace(
        "https://*.ssl-images-amazon.com", ""), images   # 任意のホストは許さない
    assert "http://" not in images, images               # 平文で画像を取りに行かない
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
                 "history.css", "history.js", "sharing.js", "legal.css"]:
        response = client.get(f"/assets/{name}")
        assert response.status_code == 200, name
    assert client.get("/theme.js").status_code == 200
    for path in PAGES:
        page = page_source(path)
        assert "cdn." not in page, path
        assert "unpkg" not in page, path


def test_creators_api_state_reaches_the_operator_screen_only():
    """商品APIの状態は運営者だけのもの。公開版の訪問者へ渡さない。

    広告を有効にした公開版では affiliate 一式が訪問者にも返る。そこへ相乗りさせると、
    運営者のアソシエイト口座の事情 (適格販売が足りない等) が外へ出る。
    """
    source = page_source("/settings")
    assert "function renderCreatorsState(state)" in source
    assert 'id="creators-api-state"' in source
    assert "Amazonが受け付けていません" in source
    # 呼ぶ前に「正常」と書かない
    assert 'if(!state||typeof state.ok!=="boolean"){box.hidden=true' in source

    body = client.get("/api/settings").json()
    assert "creators_api_state" in body, "運営者用では返すこと"

    reloaded = importlib.reload(main)
    try:
        reloaded.PUBLIC_MODE = True
        public_client = TestClient(reloaded.app, base_url="http://localhost")
        assert "creators_api_state" not in public_client.get("/api/settings").json()
    finally:
        importlib.reload(main)


def test_no_route_is_defined_twice():
    """同じ経路を二度定義しない。後ろの定義は到達せず、直したつもりが効かない。

    /affiliate/click, /api/affiliate/click, /api/amazon/products が丸ごと二重に
    書かれていた。中身が同じうちは無害だが、片方だけ直した日に静かに裏切る。
    """
    from collections import Counter
    seen = Counter((route.path, tuple(sorted(getattr(route, "methods", None) or [])))
                   for route in main.app.routes)
    assert [key for key, count in seen.items() if count > 1] == []


def test_protected_species_states_the_fact_without_granting_collection():
    """種の保存法の指定は事実だけを出す。規制の中身は指定の種類で違い、要約すると外す。"""
    source = page_source("/")
    assert "function protectedSpeciesHtml(c)" in source
    assert "c.protected_species" in source
    assert "種の保存法の" in source
    assert "https://www.env.go.jp/nature/kisho/domestic/list.html" in source
    # 版を明かす。同梱したリストが古ければ、読み手がそれを見て判断できる
    assert "p.as_of" in source
    # 採取の可否は述べない。安全カードの「確認が必要」を上書きしない
    for granted in ["採取できます", "持ち帰れます", "採取可能", "規制対象ではありません", "指定はありません"]:
        assert granted not in source, granted


def test_protected_species_is_silent_on_a_non_match():
    """一致しなかった候補には何も出さない。都道府県の条例が独自に指定している種があり、
    亜種で指定されているものは種名では当たらないため、無印は「指定なし」ではない。"""
    for script in ["/assets/index.js", "/assets/history.js"]:
        source = client.get(script).text
        assert 'if(!p||!p.category)return ""' in source, script


def test_history_also_shows_the_protected_designation():
    """指定を見落として持ち帰るのは、結果を見た日とは限らない。"""
    source = page_source("/history")
    assert "function protectedBadge(c)" in source
    assert "+protectedBadge(c)+" in source
    assert "https://www.env.go.jp/nature/kisho/domestic/list.html" in source


def test_stylesheets_define_every_token_they_use():
    """そのページで未定義の var() を参照しないこと。

    未定義のトークンを参照した宣言は、エラーにならず静かに落ちる。実際に
    /（.photo-notes）と /history（.save-state）が、settings.css 側の名前
    (--color-line, --radius-control) を書いたまま枠も背景も付かない状態で
    動いていた。名前を1つ間違えただけで見た目が消えるので、目視では気づけない。
    """
    for path in PAGES:
        html = client.get(path).text
        sheets = [client.get(href).text
                  for href in re.findall(r'href="(/assets/[^"]+\.css)"', html)]
        defined = {name for sheet in sheets for name in re.findall(r"(--[\w-]+)\s*:", sheet)}
        used = {name for sheet in sheets for name in re.findall(r"var\((--[\w-]+)", sheet)}
        assert not used - defined, (path, sorted(used - defined))


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
        # 「更新履歴」はアプリの更新のことで、観察の記録とは別のもの。ここで
        # 禁じているのは、観察の記録を「履歴」とも呼んでしまう言い換え。
        visible = visible.replace('<a href="/changelog">更新履歴</a>', "")
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
    label = "植物にくわしいサービスにも聞く"
    assert label in client.get("/").text
    assert label in client.get("/settings").text


def test_privacy_policy_matches_where_deletion_actually_lives():
    """書いてある消し方が、画面に本当にあること。"""
    privacy = client.get("/privacy").text
    assert "設定画面・履歴画面から利用者が削除できます" not in privacy
    assert "「調べた記録」の画面から、記録を1件ずつ利用者が削除できます" in privacy
    # まとめて消す手段は画面に持たないので、代わりの行き先を書く
    assert "サイトデータを削除" in privacy
    for path in ["/settings", "/history"]:
        assert "すべて削除" not in page_source(path), path


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
    for path in ["/", "/settings", "/history", "/privacy", "/terms", "/changelog",
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
                        ("/terms", f"利用規約 · {APP_NAME}"),
                        ("/changelog", f"更新履歴 · {APP_NAME}")]:
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
    products = client.get("/assets/products.js").text
    assert 'detail.addEventListener("toggle",load)' in history
    assert "if (shell.dataset.loaded) return" in products   # 開き直しで再取得しない
    assert "if(detail.open){loadProducts(record,shells);pullPhotosIfMissing(record,node)}" in history


def test_product_shelf_logic_is_shared_by_both_screens():
    """商品まわりを画面ごとに書かない。

    食品の除外と切り口の使い分けは記録画面にしかなく、撮影画面には素の検索語しか
    なかった。安全カードが「食べられるかは判定しません」と言っているのは撮影画面の
    ほうなので、除外が要るのもそちら側だった。productCard も二重に書かれていた。
    """
    for page in ["/", "/history"]:
        assert 'src="/assets/products.js"' in client.get(page).text, page
    products = client.get("/assets/products.js").text
    index = client.get("/assets/index.js").text
    history = client.get("/assets/history.js").text
    for name in ["function productCard(", "function productQueries(", "function looksEdible(",
                 "function shuffle(", "const EDIBLE_WORDS"]:
        assert name in products, name
        assert name not in index, (name, "index.js に写しが残っている")
        assert name not in history, (name, "history.js に写しが残っている")


def test_record_ads_show_several_products_with_pictures():
    products = client.get("/assets/products.js").text
    assert "function productCard(product)" in products
    assert 'class="product-image"' in products and 'class="product-grid"' in products
    assert 'rel="sponsored noopener noreferrer"' in products
    assert '広告 · ' in products                              # 広告と明示する
    for css_path in ["/assets/history.css", "/assets/index.css"]:
        css = client.get(css_path).text
        assert ".product-grid{" in css and ".product-card{" in css, css_path


def test_record_ads_prefer_the_species_over_generic_field_guides():
    """「分類+図鑑」は必ずヒットするので、先に置くとどの候補でも同じ図鑑が並ぶ。"""
    products = client.get("/assets/products.js").text
    assert "function productQueries(name, scientificName, category)" in products
    assert "shuffle(specific).slice(0, 3)" in products      # 種名の切り口を先に、順はランダム
    assert 'specific.push({ q: name, index: "Books" })' in products   # その種を扱った本
    assert '{ q: category + " 図鑑", index: "Books", generic: true }' in products
    # 一般書は枠を埋める保険。多くても2件までにして種固有の品を押しのけない
    assert "shuffle(found.generic).slice(0, 2)" in products
    assert "product-fallback" in client.get("/assets/products.js").text  # 検索リンクは共有側にある
    assert "product-fallback" in client.get("/assets/index.js").text     # APIを待つ前から出しておく


def test_record_ads_keep_food_away_from_the_safety_warning():
    """「食べられるかは判定しません」の隣に食品を並べない。誤同定のとき危険な後押しになる。"""
    products = client.get("/assets/products.js").text
    assert "function looksEdible(title)" in products
    assert "EDIBLE_WORDS" in products
    for word in ["茶", "食用", "乾燥", "サプリ", "おやつ"]:
        assert f'"{word}"' in products, word
    assert "looksEdible(product.title)" in products
    # 種名だけで引くと食品が上位に来るため、用途を添える
    assert 'specific.push({ q: name, index: "All" })' not in products
    assert 'name + " 観察"' in products


def test_record_ads_drop_duplicates_by_title_too():
    """同じ品が別URLで返ることがある。"""
    products = client.get("/assets/products.js").text
    assert "budget.seen.has(product.url)" in products and "budget.seen.has(key)" in products


def test_product_images_are_allowed_by_the_policy():
    policy = client.get("/history").headers["content-security-policy"]
    assert "https://*.media-amazon.com" in policy


def test_history_coordinates_are_rendered_only_by_the_detail_builder():
    history = client.get("/assets/history.js").text
    render_source = history.split("async function render()", 1)[1].split("function detailPhotos", 1)[0]
    assert "coordinates" not in render_source
    assert "function coordinateDetail(e)" in history
    assert "function rowLocation(e)" in history
    assert 'coordinateLocation(location)?""' in history
    assert "(location?" in history
    assert "x.location&&!coordinateLocation(x.location)" in history
    assert history.count("coordinateDetail(e)") == 2
    assert "位置：" in history and "（おおまかな値）" in history


def test_records_can_be_examined_again():
    """元の写真は残っていないので、保存済みの縮小画像を送り直す。"""
    history = client.get("/assets/history.js").text
    assert "async function reidentify(record,button,message,selection=null)" in history
    assert "const keptIndexes=Array.isArray(selection?.keptIndexes)" in history
    assert 'kept.forEach((blob,i)=>fd.append("files",blob,"photo-"+(i+1)+".jpg"))' in history
    assert 'e.thumbnail?\'<button class="btn again"' in history   # 写真が無い記録には出さない
    assert "調べ直しています…" in history
    # 公開版は BYOK。撮影画面と同じ形でキーとモデルを渡す
    for field in ["request_provider", "request_model", "request_api_key", "request_plantnet_key"]:
        assert field in history, field
    # 元の記録は消さず、新しい記録として足す（前後を見くらべられる）
    assert "async function saveRerun(source,data,photos=[])" in history
    assert "rerunOf:source.id" in history
    assert "thumbnail:photos[0]||source.thumbnail||null,thumbnails:photos," in history
    assert "coordinates:source.coordinates" in history
    assert ".slice(50)" in history   # 上限50件は撮影画面と同じ


def test_each_candidate_owns_its_advert():
    """広告の帰属は位置で決める。巡回させない。

    最初は1つの棚が候補間を巡回しており、どの候補の広告なのか読み手に分からなかった。
    次に第一候補へ固定したが、棚は全候補の後ろにあり、結びつきは順序の暗黙知だった。
    いまは候補のブロックの中に置く。名前もラベルに入れて、位置と文字の両方で言い切る。
    そのぶん決め手のない候補にも広告が付くので、候補名を出す約束は外せない。
    """
    index = client.get("/assets/index.js").text
    assert "affiliateProductLink(c,data.category)+'</article>'" in index  # 候補の中に置く
    assert "topCandidateAffiliateLink" not in index      # 全候補の後ろの1棚をやめた
    assert "affiliateCursor" not in index                # 巡回はしない
    assert "candidates[0]" not in index
    assert '"Amazonで"+shell.dataset.name+"の関連商品"' in index  # ラベルに候補名を入れる
    history = client.get("/assets/history.js").text
    # 記録側も同じ約束。候補ごとの棚を、その候補の <li> の中に入れる
    assert "item.append(shell)" in history
    assert 'label:"Amazonで"+(name||"関連商品")+"の関連商品"' in history
    assert "Math.floor(Math.random()*named.length)" not in history


def test_candidate_adverts_stay_within_a_request_budget():
    """候補ごとに棚を持つと、識別1回で商品APIを何度も叩く。上限と順序を決めておく。"""
    index = client.get("/assets/index.js").text
    products = client.get("/assets/products.js").text
    assert "function productBudget(maxRequests = 6, perShelf = 2)" in products
    assert "budget.left <= 0" in products                # 通しの予算が切れたら打ち切る
    assert "budget.left--" in products
    # 棚ごとの上限もいる。通しだけだと最初の候補が使い切り、3番目が1回も引けない
    assert "used >= budget.perShelf" in products
    # まとめて投げない。上の候補から順に使う (下の候補ほど確からしさが低い)
    assert "for(const shell of document.querySelectorAll" in index
    assert "await loadProductShelf(shell," in index
    assert "Promise.all" not in index
    # 集めた品は棚をまたいで覚える。どの候補でも当たる一般書が3つ並ぶのを防ぐ
    assert "budget.seen.add(product.url)" in products


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


def test_user_observation_notes_are_separate_safe_and_persistent():
    history = client.get("/assets/history.js").text
    backup = client.get("/assets/backup.js").text
    css = client.get("/assets/history.css").text
    assert 'class="observation-note"' in history
    assert 'class="note-input"' in history
    assert "NOTE_MAX_LENGTH=2000" in history
    assert 'esc(e.userNote||"")' in history       # textareaへHTMLを差し込まない
    assert "userNote:String(value).slice(0,NOTE_MAX_LENGTH)" in history
    assert "noteUpdatedAt:new Date().toISOString()" in history
    assert "scheduleAutoBackup()" in history
    assert ".observation-note" in css
    # 古いDrive側の値で、端末内の新しいメモや空欄への変更を潰さない
    assert "existingNoteAt > incomingNoteAt" in backup
    assert "entry.userNote = existing.userNote" in backup


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
    # 先頭を必ず別の文字にする。"x" 決め打ちだと、元の署名が x で始まったとき
    # 差し替えても同じ文字列になり、改竄を弾けていないのに通ってしまう (1/64 で揺れた)
    other = "y" if signature[0] == "x" else "x"
    assert auth.read_session(body + "." + other + signature[1:]) is None
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
    for path in ["/login", "/privacy", "/terms", "/changelog", "/api/me"]:
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
    assert "/privacy" in page and "/terms" in page and "/changelog" in page


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
    """記録するたび許可を求められては使い物にならない。

    以前ここは「二度目からは黙って取り直す」と書いてあり、その思い込みが
    popup_failed_to_open の原因だった。GIS に画面を出さない取得は無い。
    許可を求めずに済ませる方法は、取り直しを減らすこと (トークンをタブ内で
    持ち回す) であって、黙って窓を開けようとすることではない。
    """
    drive = client.get("/assets/gdrive.js").text
    assert 'requestAccessToken({prompt: "consent"})' in drive
    assert "silent" not in drive                 # 画面を出さない取得は無い
    assert "async function autoSaveToDrive()" in drive
    assert "const DRIVE_TOKEN_KEY" in drive      # 画面を移っても持ち回す
    backup = client.get("/assets/backup.js").text
    assert "if (typeof autoSaveToDrive === \"function\") autoSaveToDrive();" in backup
    # 覚えるのは「一度つないだ」という事実。トークンはタブを閉じれば消える
    assert "species-drive-linked" in drive
    assert "localStorage.setItem(DRIVE_TOKEN_KEY" not in drive


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
    assert packages == {"fastapi", "uvicorn", "httpx", "pillow", "pillow-heif", "python-multipart"}, packages
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
    assert security.count("<li") >= 5, "中身が減っている"


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


def test_how_to_tell_them_apart_is_always_shown():
    """実測で6割は種を外し (Top-1 40%)、その多くは属まで合っている。
    「アオダイショウです」と言い切られて違うより、「シマヘビとはここで見分ける」が
    添えてあるほうが、実物と見くらべられる。

    以前は evidence_status が uncertain のときだけ出す作りで、しかも traits があると
    手前で return して、一度も表示されていなかった。"""
    script = client.get("/assets/index.js").text
    body = script.split("function evidenceHtml(c){")[1].split("\n}")[0]
    # 確信の度合いで見分け方を出し分けない
    assert "似ている種との見分け方" in body
    assert body.index("points.length?") > body.index("const unsure=")
    # 手前で返さない
    assert "return c.traits.length?" not in body


def test_api_keys_never_leave_the_browser():
    """ドライブに置くのは記録と設定だけ。キーはブラウザのパスワード管理に預ける。
    同じものを二重に持つと、片方が漏れる筋が増える。"""
    backup = client.get("/assets/backup.js").text
    assert "apiKeys" not in backup.split("async function restoreBackup")[0]  # 書き出しに入れない
    assert "collectApiKeys" not in backup and "savingKeys" not in backup
    assert "APIキーは含めない" in backup
    page = client.get("/settings").text
    assert 'id="save-keys"' not in page          # 選択肢そのものを置かない
    privacy = client.get("/privacy").text
    assert "Google ドライブへ保存する記録にも含めません" in privacy
    assert "ブラウザのパスワード管理に預けた場合" in privacy


def test_one_name_per_number():
    """同じ c.confidence に「あてはまり度」と「写真からのAI推測 最大」の2つの名前を
    付けていた。利用者には別の指標に見える。"""
    script = client.get("/assets/index.js").text
    body = script.split("function confidenceView(c){")[1].split("\n}")[0]
    assert body.count("あてはまり度") == 1
    assert "写真からのAI推測" not in body
    assert "決め手は足りていません" in body      # 弱いことは別に伝える


def test_the_words_stay_the_same_across_screens():
    """1つのことを指す言葉は1つにする。「識別」「判定」は利用者向けの画面から外し、
    「調べる」に寄せた。ただし安全カードの「判定しません」は残す。意図的にやらない
    という宣言で、「調べません」より意味がはっきりする。"""
    for path in ["/", "/settings", "/history", "/login"]:
        page = client.get(path).text
        visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
        visible = " ".join(re.findall(r">([^<>]+)<", visible))
        assert "植物専用の識別" not in visible, path
        assert "判定時" not in visible, path
    # 安全カードだけは「判定しません」を保つ
    assert "判定しません" in client.get("/assets/index.js").text


def test_operator_records_travel_but_do_not_mix_with_visitors():
    """運営者用の記録も端末をまたいで同じものにする。ただし利用者の記録とは分ける。

    以前は運営者用の書き込みごと止めていた。理由は「試し撮りが利用者の記録に混ざると
    見分けがつかない」で、混ざるのは保存先が同じファイルだったから。書き込み自体が
    悪かったのではない。止めていた間、運営者用の記録はその端末から出られなかった。
    """
    page = client.get("/settings").text     # 既定は運営者モード
    section = page.split('aria-labelledby="backup-heading"')[0]
    assert not section.rstrip().endswith('data-only="public"'), "運営者用で記録の保存が隠れている"
    backup = client.get("/assets/backup.js").text
    guard = backup.split("function scheduleAutoBackup() {")[1].split("backupTimer = setTimeout")[0]
    assert 'document.body.dataset.appMode !== "public"' not in guard
    drive = client.get("/assets/gdrive.js").text
    assert 'operator: "ikimono-note-operator.json"' in drive
    assert 'public: "ikimono-note.json"' in drive
    assert "function driveFileName()" in drive
    # 固定名のまま書き込むと、モードを分けた意味がなくなる
    assert "name: driveFileName()" in drive
    assert "${driveFileName()}" in drive


def test_deleting_a_record_asks_first():
    """1件の削除に確認がなかった。押し間違いで写真ごと戻せなくなる。

    すべて削除と退会には確認があるのに、行に並ぶ「削除」だけは即座に消していた。
    写真を残すようにしてから、1件で最大3枚が消えるようになっている。ドライブに
    つないでいれば次の自動保存で向こうからも消えるので、そこも伝える。
    """
    history = client.get("/assets/history.js").text
    assert "function confirmDelete(what)" in history
    assert "写真もいっしょに消え、元に戻せません。" in history
    # どの記録を消すのかを名前で言う
    assert 'confirmDelete("「"+title(entry||{})+"」の記録を削除しますか？")' in history
    assert 'if(!confirmDelete(' in history
    # つないでいるときだけドライブの話をする
    assert 'typeof driveLinked==="function"&&driveLinked()' in history
    assert "そちらからも消えます。" in history
    # 確認と実際の削除がひと続きであること。間に何も挟まらない書き方で固定する
    assert ('if(!confirmDelete("「"+title(entry||{})+"」の記録を削除しますか？"))return;'
            'const d=await openDb(),t=d.transaction("entries","readwrite");'
            't.objectStore("entries").delete(node.dataset.id)') in history
    assert 'objectStore("entries").clear()' not in history   # まとめて消す道は持たない
    # 上限50件の間引きは利用者が押した削除ではないので聞かない
    assert "excess.forEach(item=>tx.objectStore(\"entries\").delete(item.id))" in history


def test_every_photo_used_is_kept_and_viewable():
    """撮り足した写真も残して、あとから見返せること。

    以前は1枚目しか残しておらず、寄りの1枚は識別が済んだ時点で消えていた。
    一覧のサムネイルは1枚目だけなので、残りは詳細で見せる。
    長辺960pxのJPEGは実測の中央値33KBで、3枚×50件でもドライブのJSONは6MB台。
    """
    index = client.get("/assets/index.js").text
    assert "for(const file of selected)" in index          # 選んだ全部を縮小する
    assert "const thumbnail=thumbnails[0]||null;" in index  # 一覧用の1枚は据え置き
    assert "coordinates,thumbnail,thumbnails,listThumbnail}" in index
    history = client.get("/assets/history.js").text
    assert "function recordPhotos(record)" in history       # 旧形式は thumbnail 1枚
    assert "return record?.thumbnail?[record.thumbnail]:[]" in history
    assert "function detailPhotos(e)" in history
    assert 'class="photo detail-photo"' in history
    assert ".detail-photos{" in client.get("/assets/history.css").text
    # 別の端末へも渡す。原寸はドライブの別ファイル、一覧用の小さい1枚はJSONに入れる
    backup = client.get("/assets/backup.js").text
    assert "record.thumbnails.map(dataUrlToBlob).filter(Boolean)" in backup
    assert "copy.listThumbnail = small ? await blobToDataUrl(small) : null" in backup
    assert "async function fetchRecordPhotos(record)" in client.get("/assets/gdrive.js").text


def test_the_drive_json_carries_thumbnails_not_full_photos():
    """1つのJSONに原寸を詰めない。タブを開くたびに十数MBを引くことになる。

    予算で古い記録の写真を落としていたのをやめ、原寸はドライブの別ファイルへ出した。
    JSONには一覧用の320pxと、置き場の札だけを入れる。全部の記録に絵が付く。
    """
    backup = client.get("/assets/backup.js").text
    assert "const LIST_MAX_EDGE = 320" in backup
    assert "copy.listThumbnail = small ? await blobToDataUrl(small) : null" in backup
    assert "copy.thumbnail = null;" in backup and "copy.thumbnails = [];" in backup
    assert "copy.drivePhotos =" in backup
    assert "BACKUP_PHOTO_BUDGET" not in backup     # 予算で落とす方式はやめた


def test_full_photos_live_in_their_own_drive_files():
    """原寸は記録ごとに別ファイル。上げ直すのは変わったぶん、引くのは開いたぶんだけ。"""
    drive = client.get("/assets/gdrive.js").text
    assert 'const PHOTO_PREFIX = "ikimono-photo-"' in drive
    assert "function photoFileName(recordId, index)" in drive
    assert "async function uploadPendingPhotos()" in drive
    assert "async function fetchRecordPhotos(record)" in drive
    assert "async function pruneDrivePhotos()" in drive
    # 1回の保存で上げる枚数を抑える (50件×3枚を一度に上げない)
    assert "const PHOTO_UPLOADS_PER_SAVE = 6" in drive
    # 札を JSON に載せるので、上げるのは JSON を作る前
    upload = drive.index("await uploadPendingPhotos()")
    build = drive.index("const payload = await buildBackup()")
    assert upload < build, "札が JSON に入らない順序になっている"
    # 記録が消えたぶんは片付ける
    assert 'name contains \'${PHOTO_PREFIX}\'' in drive
    assert "alive.has(file.id)" in drive


def test_the_preview_uses_the_space_it_has():
    """「写真を確認」はピントと被写体の位置を見る場所。3列固定だと小さすぎた。

    1枚でも横幅の3分の1しか使わず、携帯では110pxほどだった。写真の解像度は
    元のまま (createObjectURL) なので、足りていなかったのは表示枠のほう。
    """
    index = client.get("/assets/index.js").text
    assert 'previews.className="previews count-"+selected.length' in index
    assert "URL.createObjectURL(file)" in index          # 元の解像度のまま見せる
    css = client.get("/assets/index.css").text
    assert ".previews{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))" in css
    assert ".previews.count-1 .preview{height:min(58vh,440px)}" in css
    assert "repeat(3,minmax(0,1fr))" not in css          # 3列固定はやめた


def test_the_send_size_can_be_measured_not_just_asserted():
    """外部AIへ送る長辺は振れるようにする。効くかどうかは測らないと分からない。

    eval の写真は長辺500pxで、この上限 (1600) に一度も届いていなかった。
    つまり既存の結果はどれも本番より小さい写真での成績になっている。
    """
    assert "IKIMONO_MAX_EDGE" in (Path(__file__).parents[1] / "vision.py").read_text(encoding="utf-8")
    fetcher = (Path(__file__).parents[1] / "eval" / "fetch_dataset.py").read_text(encoding="utf-8")
    assert "IKIMONO_EVAL_PHOTO_SIZE" in fetcher
    assert '{"medium", "large", "original"}' in fetcher
    assert 'f"/{SIZE}."' in fetcher


def test_the_list_says_how_sure_each_record_is():
    """一覧が候補を断定に見せていた。

    行は候補名を太字で出すだけで、60%「2つの方法で確認」も30%「決め手なし」も
    同じ見た目だった。結果画面が守っている「これは候補である」という約束を、
    一覧だけが破っていた。記録は後日読み返すもので、確からしさの記憶は消えている。
    """
    history = client.get("/assets/history.js").text
    assert "function rowMarks(e)" in history
    assert "const ROW_STATUS=" in history
    for word in ["2つの方法で確認", "決め手なし", "写真からの推測", "植物のサービスだけが答えた"]:
        assert word in history, word
    assert "esc(title(e))+rowMarks(e)" in history      # 行の見出しに添える
    assert ".row-marks{" in client.get("/assets/history.css").text


def test_a_record_with_no_candidate_does_not_look_like_a_species():
    """候補ゼロのとき分類名に落ちると、「菌類」という名前の生きものに見えた。"""
    history = client.get("/assets/history.js").text
    assert '"候補が見つかりませんでした"' in history
    assert 'e.candidates?.[0]?.common_name_ja||e.category' not in history
    # 分類は見出しではなく印のほうへ回す
    assert 'if(!top)marks.push(\'<span class="badge">\'+esc(e.category||"分類なし")' in history


def test_a_protected_species_is_visible_without_opening_the_record():
    """法律に関わる唯一の事実が、開かないと出てこないのはおかしい。"""
    history = client.get("/assets/history.js").text
    assert 'c?.protected_species?.category' in history
    assert '種の保存法の指定</span>' in history
    assert ".badge.protected-mark{" in client.get("/assets/history.css").text


def test_the_row_shows_the_small_one_but_opens_the_full_one():
    """行に出すのは小さいほう、押して開くのは原寸。

    同じものを両方に使っていたため、拡大すると320pxが引き伸ばされて出ていた。
    行は80pxで50行ぶん展開するので小さいほうが要り、拡大は原寸でなければ意味がない。
    """
    history = client.get("/assets/history.js").text
    assert "const full=recordPhotos(e)[0]||null;const small=e.listThumbnail||full;" in history
    assert 'data-src="\'+large+\'"' in history       # 押して開くのは原寸
    assert '<img class="thumb" src="\'+image+\'"' in history  # 行に出すのは小さいほう
    # 原寸が手元にない記録は、押されたときに引いて差し替える
    assert "const photos=await pullPhotosIfMissing(record,b.closest(\"article\"))" in history
    assert "if(photos&&photos[0])$(\"large\").src=URL.createObjectURL(photos[0])" in history
    index = client.get("/assets/index.js").text
    assert "shrinkForHistory(thumbnail,LIST_MAX_EDGE)" in index
    assert "listThumbnail}" in index


def test_the_shrink_helper_is_shared_by_both_screens():
    """縮小は撮影画面と記録画面の両方が要る。写しを2つ持たない。"""
    backup = client.get("/assets/backup.js").text
    assert "async function shrinkForHistory(file,edge=HISTORY_MAX_EDGE)" in backup
    # 保存はサーバーが外部AIへ送る上限と同じ。低いと調べ直しだけ不利になる
    assert "const HISTORY_MAX_EDGE = 1600" in backup
    assert str(main.vision.MAX_EDGE) == "1600"
    assert "Math.min(1,edge/Math.max(bitmap.width,bitmap.height))" in backup
    for name in ["index.js", "history.js"]:
        assert "async function historyThumbnail" not in client.get(f"/assets/{name}").text, name


def test_the_hidden_attribute_actually_hides_on_every_page():
    """hidden 属性は .btn の display:inline-flex に負ける。

    設定画面には [hidden]{display:none!important} があったが記録画面にはなく、
    調べ直すボタンが写真を足す前から出ていた。クラスの .hidden だけでは足りない。
    """
    for name in ["settings.css", "history.css"]:
        css = client.get(f"/assets/{name}").text
        assert "[hidden]{display:none!important}" in css, name


def test_the_drive_connection_renews_itself():
    """つないだあと切れっぱなしにしない。

    Google のアクセストークンは1時間ほどで切れる。期限を見ずに持ち続けていたので、
    タブを開いたまま1時間たつと最初の書き込みが 401 で落ちていた。期限を持ち、
    タブの中で持ち回すことで、1時間のあいだは画面を移っても切れない。

    切れたあとの取り直しは、押されたときだけ。黙って取り直す道は無い
    (GIS は必ずポップアップを開くので、押されていなければ止められる)。
    """
    drive = client.get("/assets/gdrive.js").text
    assert "let driveTokenExpiry = 0;" in drive
    assert "function driveTokenAlive()" in drive
    assert "Date.now() < driveTokenExpiry" in drive
    # 期限は Google が返す expires_in から。手前で切れた扱いにする
    assert "Math.max(0, Number(response.expires_in || 3600) - 60) * 1000" in drive
    # 期限内は取り直さない
    assert "if (driveTokenAlive()) return driveToken;" in drive
    # 画面を移っても消えない。ただしタブを閉じれば消える
    assert "sessionStorage.setItem(DRIVE_TOKEN_KEY" in drive
    assert "function recallDriveToken()" in drive
    # 401 でこっそり取り直さない。窓を開ける操作なので、押されていなければ止められる
    assert "return await driveFetch(url, options, {retried: true});" not in drive
    assert "設定画面でもう一度つないでください" in drive
    assert "let driveClientId" in drive       # つなぎ直しに要る
    # 取り直せるかどうかは、画面には正直に出す
    assert "return driveTokenAlive();" in drive


def test_a_failed_drive_refresh_says_why():
    """「つなぎ直しが必要です」だけでは、次に切れても同じ調査になる。

    prompt:"none" が通らない理由は、サードパーティCookie、Google側のセッション切れ、
    同意の取り消し、OAuth同意画面がテスト中で期限切れ、と何通りもある。Google が
    何と言ったかを残さないと、どれなのか分からない。
    """
    drive = client.get("/assets/gdrive.js").text
    assert "let lastDriveTokenError" in drive
    assert "function driveTokenTrouble()" in drive
    assert 'console.info("ドライブのトークンを取り直せませんでした", error)' in drive
    assert 'noteDriveStatus(false, "つなぎ直しが必要です" + (driveTokenTrouble()' in drive
    settings_js = client.get("/assets/settings.js").text
    assert 'typeof driveTokenTrouble==="function"?driveTokenTrouble():""' in settings_js


def test_drive_tokens_are_not_requested_in_parallel():
    """並行で投げると、あとの initTokenClient が先の要求のコールバックを捨てる。

    設定画面では「開いたときの取り込み」と「画面の状態を描く」が同時に走る。
    """
    drive = client.get("/assets/gdrive.js").text
    assert "let driveTokenRequest = null;" in drive
    assert "if (driveTokenRequest) return driveTokenRequest;" in drive
    assert "driveTokenRequest = null;" in drive.split("finally")[1][:120]


def test_the_screen_names_the_ai_that_actually_ran():
    """Gemini を選んでいるのに Ollama と出ていた。

    loadSettings が providerLabel(provider) を呼びながら戻り値を捨てており、
    providerName は初期値の "Ollama" のまま一度も更新されなかった。ヘッダー、
    待っているあいだの表示、そして記録に残す provider まで全部が嘘になる。
    DESIGN.md が「使うAIは実物の名前で言う」と決めているのはここのこと。
    """
    index = client.get("/assets/index.js").text
    assert "providerName=providerLabel(provider);" in index
    assert "providerLabel(provider);" not in index.replace("providerName=providerLabel(provider);", "")
    # 記録にもその名前が入る
    assert "provider:providerName" in index
    links = client.get("/assets/species-links.js").text
    assert 'gemini: "Gemini"' in links and 'local: "Ollama"' in links


def test_waiting_is_visible_where_the_answer_will_appear():
    """処理中が分かりづらかった。status 行は撮影パネルの下にあり、目に入らない。"""
    index = client.get("/assets/index.js").text
    assert "function showWorking(startedAt)" in index
    assert "が写真を見ています（\"+seconds+\"秒）" in index      # 止まっていないことを秒で示す
    assert "setInterval(tick,1000)" in index
    assert "$('results').className='placeholder working'" in index  # 答えが出る場所にも出す
    assert '<span class="spinner"></span>' in index
    assert ".placeholder.working{" in client.get("/assets/index.css").text
    # 待っているあいだは押せない
    assert "identify.disabled=true" in index


def test_the_visitor_learns_the_limit_before_hitting_it():
    """1日3回だと知らずに2回使い、3回目で初めて壁に当たるのは不親切。

    続ける道 (自分のキーを入れる) も一緒に出す。自分のキーを持っている人には出さない。
    """
    index = client.get("/assets/index.js").text
    assert "function showTrialNote(data)" in index
    assert '"このまま1日"+trial.per_day+"回まで試せます。' in index
    assert 'const hasKey=Boolean(readApiKey("gemini")' in index
    assert 'if(!trial||hasKey){note.classList.add("hidden");return}' in index
    assert 'id="trialNote"' in client.get("/").text
    assert ".trial-note{" in client.get("/assets/index.css").text


def test_an_anonymous_visitor_can_find_the_way_in():
    """記録を端末をまたいで残したい人が、ログインの入り口を見つけられないままになる。"""
    index = client.get("/assets/index.js").text
    assert "async function showSignIn()" in index
    assert 'me.available&&!me.signed_in' in index      # 未ログインのときだけ
    assert 'id="signInLink"' in client.get("/").text
    assert 'href="/login"' in client.get("/").text


def test_the_trial_opens_the_whole_round_trip_not_just_the_start():
    """識別は始まるのに結果を取りに行けない、という開け方をしない。

    札の問い合わせ先 (/identify/job/<id>) を閉じたままにしていたため、ポーリングが
    ログイン画面のHTMLを受け取り「Unexpected token '<'」で終わっていた。実測で
    181秒待たされて失敗し、開けたあとは14秒で候補が出た。
    """
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'or path.startswith("/identify/job/")' in source


def test_the_screen_names_the_model_the_trial_actually_runs():
    """お試し枠で走るモデルは利用者が選んだものではない。

    画面が別の名前を出したままだと、どのAIに写真が行くのかを偽ることになる。
    実測で、キーを持たない訪問者の画面は gemini-3.6-flash と出ていたが、
    実際に走っていたのは gemini-3.5-flash-lite だった。
    """
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'result["trial"] = {"per_day": TRIAL_PER_DAY, "provider": "gemini", "model": TRIAL_MODEL}' in source
    index = client.get("/assets/index.js").text
    assert "window.speciesTrial=data.trial||null;" in index
    assert "model=window.speciesTrial.model;" in index
    # 自分のキーを持っている人には、選んだものをそのまま出す
    assert "!readApiKey(window.speciesTrial.provider)&&!readApiKey(provider)" in index


def test_per_visitor_limits_see_the_visitor_not_the_proxy():
    """公開版は 127.0.0.1 で待ち受け、前段だけがつながる。

    request.client.host は常に前段のアドレスなので、全員が同じIPに見える。この状態で
    IPごとの制限をかけると、1分6回も1日N回も「全利用者の合計」になり、最初の1人が
    使い切ると他の全員が閉め出される。実測でも Funnel 越しに 100.94.207.13 が見えていた。
    """
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert "def _client_ip(request: Request)" in source
    assert 'request.headers.get("x-forwarded-for", "")' in source
    assert source.count("_client_ip(request)") == 2      # レート制限とお試し枠の両方
    assert "request.client.host" not in source.split("def _client_ip")[1].split("def _rate_limit")[1]
    # 運営者用では読まない。0.0.0.0 で待つので、ヘッダを名乗るだけで別人になれる
    assert "if PUBLIC_MODE:" in source.split("def _client_ip")[1][:400]


def test_a_stranger_can_try_it_once_when_the_operator_opens_a_trial():
    """公開版は BYOK で、自分のキーが無いと1枚も調べられない。

    ログインを外しても、入り口の次に「APIキーを登録してください」が立っているだけで
    通りすがりの人には何も起きない。試させるには運営者の枠を分けるしかない。
    既定は 0 (無効)。運営者の枠を見知らぬ人が使うので、入れるかは運営者が決める。
    """
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert 'TRIAL_PER_DAY = max(0, int(os.getenv("IKIMONO_PUBLIC_TRIAL_PER_DAY", "0")' in source
    assert main.TRIAL_PER_DAY == 0                    # 既定は無効
    assert main.trial_enabled() is False              # 運営者用モードでも当然無効
    # 枠があるときだけ、撮影画面と識別をログインの外に出す
    assert 'if trial_enabled() and (path in {"/", "/settings", "/identify",' in source
    # 使い切った人に「設定でキーを」と案内する以上、その設定も開いていないと行き止まり
    assert '"/settings"' in source.split("if trial_enabled() and (path in")[1][:200]
    # 記録と設定はログインの内側のまま
    # 記録はログインの内側のまま
    opened = source.split("if trial_enabled() and (path in")[1][:200]
    assert '"/history"' not in opened
    # 使い切ったら、自分のキーを登録する道を案内する
    assert "今日のお試しは終わりです。" in source
    assert "if not api_key and trial_enabled():" in source
    # 運営者のキーが無ければ、数を入れても有効にならない
    assert 'return bool(config_store.load()["api_keys"].get("gemini"))' in source


def test_the_app_runs_where_there_is_no_disk_and_no_background_cpu():
    """このPCの外へ出すための3点。どれもアプリの形から来る話で、置き場によらない。

    1. 広告の設定が settings.json (ディスク) から来る
    2. ログイン情報が SQLite (ディスク) — auth.py に Firestore 経路が既にある
    3. レスポンス後に CPU を止める置き場では、後ろで走らせた識別が凍る
    """
    source = (Path(__file__).parents[1] / "config_store.py").read_text(encoding="utf-8")
    # ファイルが無い経路でも環境変数を読む (まさにその置き場でだけ空になっていた)
    assert source.count("_apply_env_affiliate(data)") == 2
    for name in ["IKIMONO_AFFILIATE_URL", "IKIMONO_AFFILIATE_PARTNER_TAG",
                 "IKIMONO_AMAZON_CREATORS_ID", "IKIMONO_AMAZON_CREATORS_SECRET"]:
        assert name in source, name
    # 上書きではなく穴埋め。運営者用の設定画面で保存したものを環境変数で戻さない
    assert 'if not data["affiliate"].get(field):' in source

    auth_source = (Path(__file__).parents[1] / "auth.py").read_text(encoding="utf-8")
    assert auth_source.count("if using_firestore():") == 3   # 読み・書き・削除の3経路

    main_source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    assert "BACKGROUND_JOBS = os.getenv" in main_source
    assert "if background and BACKGROUND_JOBS:" in main_source


def test_the_screen_works_without_a_job_ticket():
    """札が返らない置き場では、返ってきたものが結果そのもの。"""
    index = client.get("/assets/index.js").text
    assert "if(!data.job){stopWorking();await finishIdentification(data," in index
    history = client.get("/assets/history.js").text
    assert "if(!data.job){" in history
    assert "await saveRerun(record,data,selected)" in history


def test_identification_survives_a_reload():
    """画面を更新しても続きから受け取れること。両方の画面で。"""
    index = client.get("/assets/index.js").text
    assert 'const PENDING_KEY="species-pending-identify"' in index
    assert 'fd.append("background","true")' in index
    assert '"/identify/job/"+encodeURIComponent(pending.job)' in index
    assert "const pending=readPending();" in index
    assert "if(!pending?.job)return;" in index                 # 開いたときに続きを聞く
    # 更新すると選んだファイルも入力欄も消える。投げる前に控えておく
    assert "async function pendingPhotos()" in index
    assert "await blobToDataUrl(blob)" in index
    assert "const coordinates=gps?{latitude:" in index
    assert "const pendingContext=pending?.context||" in index
    history = client.get("/assets/history.js").text
    assert 'const RERUN_PENDING_KEY="species-pending-rerun"' in history
    assert "function resumeRerun()" in history
    assert ".then(resumeRerun)" in history
    assert "async function watchRerun(pending,button,message)" in history


def test_a_record_can_be_examined_again_with_extra_photos():
    """結果に納得できないときは、記録の中から写真を足して調べ直せること。

    旧い記録は1枚、新しい記録は最大3枚の縮小画像を持つ。元写真と追加写真から
    最大3枚を選び、元の記録を変えずに新しい記録として保存する。
    """
    history = client.get("/assets/history.js").text
    assert "function addRerunControls()" in history
    assert "const RERUN_MAX_PHOTOS=3" in history
    assert "const keptIndexes=originals.map((_,index)=>index),extras=[]" in history
    assert "RERUN_MAX_PHOTOS-keptIndexes.length-extras.length" in history
    assert "写真を足したり外したりできます" in history
    assert 'class="btn rerun-remove"' in history
    assert "調べ直す写真は1枚以上必要です。" in history
    assert "元の記録には残っています。" in history
    # カメラと写真選択の両方から足せる
    assert 'camera.capture="environment"' in history
    assert "box.querySelector(\".rerun-camera\").onclick=()=>camera.click()" in history
    assert "box.querySelector(\".rerun-library\").onclick=()=>library.click()" in history
    # 選んで残した元写真を先に、足した写真をあとに送る
    assert 'kept.forEach((blob,i)=>fd.append("files",blob,"photo-"+(i+1)+".jpg"))' in history
    assert 'extras.forEach((file,i)=>fd.append("files",file,"added-"+(i+1)+".jpg"))' in history
    # 元の記録は消さず、選んだ写真だけを新しい記録として足す
    assert "await saveRerun(source,payload.result,[...kept,...added])" in history
    assert "keptIndexes,photos:shrunk" in history
    assert "pending.keptIndexes" in history
    assert ".then(addRerunControls)" in history
    css = client.get("/assets/history.css").text
    assert ".rerun-box{" in css


def test_the_search_link_uses_the_species_name_alone():
    """検索語に分類を足さない。

    「セイヨウタンポポ 植物」で引くと、その語を含む商品へ絞られて、その種を
    扱った本や道具が落ちる。分類は言い換え (飼育/育て方) と、全滅したときの
    一般書 (分類+図鑑) でだけ使う。
    """
    products = client.get("/assets/products.js").text
    index = client.get("/assets/index.js").text
    assert "const query = name;" in products
    assert "const query=name;" in index
    assert 'name + " " + String(subject.category' not in products
    assert 'name+" "+category' not in index
    # 分類そのものを捨てたわけではない
    assert 'category === "動物" ? "飼育"' in products
    assert 'q: category + " 図鑑"' in products


def test_the_shelf_shows_cards_and_the_search_link_together():
    """画像付きカードと Amazon の検索結果、両方を出す。

    APIが返すのはその時点の上位4件までで、探し方を変えれば別のものが出る。
    カードだけにすると、そこで打ち止めに見える。「広告」の断りは棚に1回でよいので、
    カードがあるときはラベル側が担い、リンク側は繰り返さない。
    """
    products = client.get("/assets/products.js").text
    assert "function productSearchLink(subject, besideCards)" in products
    # カードの有無にかかわらず添える
    assert "+ productSearchLink(subject, collected.length > 0)" in products
    assert '"Amazonで" + esc(name) + "をもっと探す ↗"' in products          # カードと並ぶとき
    assert '"広告 · Amazonで" + esc(name) + "の関連商品を探す ↗"' in products  # 単独のとき
    assert 'rel="sponsored noopener noreferrer"' in products
    assert '/affiliate/click?q=' in products
    # 呼ぶ側は自前でリンクを組まない (二重に出る)
    history = client.get("/assets/history.js").text
    assert "product-fallback" not in history
    for css_path in ["/assets/index.css", "/assets/history.css"]:
        assert ".product-grid+.product-fallback{" in client.get(css_path).text, css_path


def test_history_ads_sit_inside_each_candidate():
    """記録から読み返すときも、どの候補の広告かを位置で決める。

    以前は記録に1棚だけで、ひもづけ先は第一候補。撮影画面を候補ごとにした以上、
    読み返す側だけ約束が違うと、同じ画面の話なのに帰属の決まり方が2通りになる。
    """
    history = client.get("/assets/history.js").text
    assert 'detail.querySelectorAll("li.candidate")' in history
    assert "async function loadProducts(record,shells)" in history
    assert "const budget=productBudget();" in history      # 1回の開閉ぶんの予算
    # 開いたときに初めて叩くのは変えない
    assert 'detail.addEventListener("toggle",load)' in history
    assert "if(detail.open){loadProducts(record,shells);pullPhotosIfMissing(record,node)}" in history
    css = client.get("/assets/history.css").text
    assert ".candidate .product-shell{" in css


def test_a_pulled_list_is_rebuilt_the_same_way_as_a_fresh_one():
    """描き直したら詳細も広告も作り直す。render だけだと簡易表示のまま広告も付かない。"""
    history = client.get("/assets/history.js").text
    restored = history.split('document.addEventListener("species-records-restored"')[1].split("});")[0]
    assert "affiliateLinksAdded=false" in restored
    assert "render().then(enrich).then(addAffiliateLinks)" in restored


def test_pulled_settings_reach_the_settings_form():
    """別の端末の設定は画面を描いたあとに届く。入れ直さないと、保存が巻き戻しになる。

    ドライブの取り込みは非同期なので、設定画面は先に描き終わっている。画面へ
    入れ直さないと、利用者が何も触らずに「保存」を押しただけで、届いた設定を古い
    表示で上書きする。そのままドライブへも書き戻るので、もう片方の端末まで巻き戻る。
    """
    settings_js = client.get("/assets/settings.js").text
    assert "const applyStored=()=>{" in settings_js
    assert 'document.addEventListener("species-records-restored"' in settings_js
    # 触りかけの入力は消さない。知らせるだけにする
    assert 'let touched=false' in settings_js
    assert '$("settingsForm").addEventListener("change",()=>{touched=true})' in settings_js
    assert "if(touched){show(" in settings_js


def test_no_manual_save_button_because_saving_is_automatic():
    """「いま保存」は要らない。押さないと保存されないように見えるボタンは害。

    記録が増減すれば scheduleAutoBackup が書き、つないだ直後にも一度書く。
    残っていた穴は設定だけ変えた場合で、そこは保存時に自動保存を促して塞ぐ。
    """
    page = client.get("/settings").text
    assert 'id="drive-save"' not in page
    assert "いま保存" not in page
    settings_js = client.get("/assets/settings.js").text
    assert "drive-save" not in settings_js
    # 設定だけ変えて調べずに閉じても、使うAIの選択がドライブへ行く
    start = settings_js.index('$("settingsForm").onsubmit=event=>{')
    end = settings_js.index('show("この端末の設定を保存しました', start)
    assert "scheduleAutoBackup();" in settings_js[start:end]
    # 残す導線: つなぐ・読み込む・解除
    for keep in ['id="drive-connect"', 'id="drive-load"', 'id="drive-forget"']:
        assert keep in page, keep


def test_the_backup_says_what_it_actually_carries():
    """「使うAIの設定も保存します」は公開版だけの話。

    運営者用のプロバイダーとモデルはサーバーの settings.json にあり、localStorage の
    species-public-settings は書かれない。buildBackup はそこしか読まないので、
    運営者用の書き出しの settings は常に null になる。記録の保存の節を運営者用でも
    出すようにした結果、この一文がその画面で嘘になっていた。
    """
    backup = client.get("/assets/backup.js").text
    assert 'localStorage.getItem("species-public-settings")' in backup
    # APIキーはどちらのモードでも書き出さない
    assert "species-key-" not in backup
    assert "APIキーは含めません" in backup
    settings_js = client.get("/assets/settings.js").text
    assert 'localStorage.setItem("species-public-settings"' in settings_js
    assert "if(data.public_mode)setupPublicSettings(data)" in settings_js

    page = client.get("/settings").text
    help_text = page.split('aria-labelledby="backup-heading"')[1].split('<p class="help">')[1].split("</p>")[0]
    assert '<span data-only="public">と、使うAIの設定</span>' in help_text
    assert 'data-only="operator">使うAIの設定はこのサーバーに保存されているので' in help_text
    assert "APIキーはどちらの場合も含めません" in help_text


def test_a_second_device_pulls_before_it_can_overwrite():
    """開いた直後に取り込む。書き込みは last-writer-wins で、統合は読み込みでしか起きない。

    取り込みを設定画面のボタンだけに任せると、別の端末で先に1件調べた瞬間、その
    少ない側でドライブのファイルが上書きされる。
    """
    drive = client.get("/assets/gdrive.js").text
    assert "async function pullFromDrive()" in drive
    assert "await loadFromDrive()" in drive
    assert "if (!drivePull) drivePull = pullFromDrive()" in drive   # 二重に引かない
    assert 'sessionStorage.getItem(DRIVE_PULLED)' in drive          # 1タブ1回
    assert 'if (!driveLinked()) return false' in drive              # つないでいなければ何もしない
    # 一覧はもう描き終わっているので、届いたら描き直す
    assert 'document.dispatchEvent(new CustomEvent("species-records-restored"' in drive
    history = client.get("/assets/history.js").text
    assert 'document.addEventListener("species-records-restored"' in history


def test_you_can_tell_what_must_be_set():
    """何を設定しなければ使えないのかが、見出しから分かるようにする。"""
    page = client.get("/settings").text
    assert '使うAIを選ぶ <span class="need required">必須</span>' in page
    assert page.count('class="need optional">任意</span>') == 2   # 追加で使えるもの / 記録の保存
    assert "設定しなくても調べられます" in page
    assert "設定しないと、記録はこの端末の中だけに残ります" in page
    # 「未登録」は必須が欠けている合図。ほかの補助文と同じ灰色では気づけない
    script = client.get("/assets/settings.js").text
    assert "APIキーが未登録です" in script
    assert 'el.dataset.missing=has?"0":"1"' in script
    css = client.get("/assets/settings.css").text
    assert '.configured:not(:empty)[data-missing="1"]' in css


def test_you_can_tell_which_screen_you_are_on():
    """ポートが違えばブラウザは別サイトとして扱い、保存領域も分かれる。それを知らないと
    行き来するたびに「設定が消えた」ように見える。"""
    page = client.get("/settings").text
    assert 'class="status-strip which-app" data-only="operator"' in page
    assert "運営者用（設定はサーバーに保存されます）" in page
    assert "公開版とはブラウザの保存領域が別です" in page
    assert "ポートが違うため" in page
    # 公開版へ渡れるようにしておく。利用者と同じ動きは、そちらでしか見られない
    assert 'href="https://ubuntu-server-app.tailf74832.ts.net/settings"' in page


def test_the_map_can_show_the_lay_of_the_land():
    """どこで見つけたかを思い出すには、道より地形が要ることがある。"""
    script = client.get("/assets/dashboard.js").text
    assert "const MAP_LAYERS={" in script
    layer_config = script.split("const MAP_LAYERS")[1].split("};")[0]
    for name in ["地図", "写真", "土地条件", "標高・起伏", "全国微地形", "土地利用"]:
        assert f'"{name}"' in layer_config, name
    for removed in ["地形", "起伏", "土地利用（1982〜83年）"]:
        assert f'"{removed}"' not in layer_config, removed
    # 出典を示せば自由に使える (政府標準利用規約)。示さないなら使えない
    assert "国土地理院" in script
    assert script.count("GSI_CREDIT+") == 5
    assert "JSHIS_CREDIT" in script and "MLIT_CREDIT" in script
    assert "L.control.layers(layers,null,{collapsed:false})" in script
    # Leaflet の表記はライブラリが自分で付ける。重ねると二重に出る
    assert "leafletjs.com" not in script.split("const MAP_LAYERS")[1].split("};")[0]


def test_the_policy_lets_the_tiles_through():
    policy = client.get("/dashboard").headers["content-security-policy"]
    images = policy.split("img-src")[1].split(";")[0]
    assert "https://cyberjapandata.gsi.go.jp" in images
    assert "https://www.j-shis.bosai.go.jp" in images
    assert "https://nlftp.mlit.go.jp" in images
    connections = policy.split("connect-src")[1].split(";")[0]
    assert "https://cyberjapandata.gsi.go.jp" in connections
    assert "https://cyberjapandata2.gsi.go.jp" in connections
    # Leaflet はタイルの隙間に 1x1 の透明 GIF を data: で置く
    assert " data:" in images
    assert "'unsafe-inline'" not in policy


def test_the_login_never_straddles_two_hostnames():
    """Cloud Run は同じサービスを新旧2つのURLで配信する。

    始めるときの state は cookie に載り、cookie はドメインごと。旧形式で始めて
    新形式へ返ると cookie が届かず「ログインできませんでした」になる。本番で実際に
    起きた。返り先は PUBLIC_ORIGIN 固定なので、入口をそこへ寄せる。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert "async def keep_one_origin(request: Request, call_next):" in source
    assert "host != CANONICAL_HOST" in source and "host in ALLOWED_HOSTS" in source
    assert "status_code=307" in source          # 本文を保つ (POST を GET に変えない)


def test_the_operator_screen_is_never_sent_to_the_public_site():
    """運営者用と公開版は PUBLIC_ORIGIN を同じ ~/.env から読む。

    入口を寄せる処理に手元からの接続を除く条件が無いと、192.168.11.9:8523 の
    運営者用画面が公開サイト (tailnet の URL) へ 307 で飛ぶ。再起動していれば
    そうなっていた。手元からの接続はそもそも Google を経由しないので寄せる理由が無い。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert "def _is_local_entry(host: str) -> bool:" in source
    assert "not _is_local_entry(host)" in source
    assert "PUBLIC_MODE and CANONICAL_HOST" in source      # 運営者用では動かさない
    for name in ("localhost", "127.0.0.1", "192.168.", "ubuntu-server-app"):
        assert name in source.split("def _is_local_entry")[1][:400]


def test_a_failed_login_says_which_check_failed():
    """理由が出ないと、本番の「ログインできませんでした」から先へ進めない。

    実際に切り分けできずに止まった。値そのものは出さない。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'print("login failed: 始めたときの cookie が届いていない", flush=True)' in source
    assert 'print("login failed: state が一致しない", flush=True)' in source
    assert 'print(f"login failed: {exc}", flush=True)' in source
    assert "state}" not in source and "{code}" not in source   # 値は残さない


def test_the_evaluation_can_run_the_same_setting_more_than_once():
    """1回の数字だけでは、ばらつきを実力の差と取り違える。

    同一設定でも第一候補が100枚中36枚入れ替わり、科以上は13ポイント動いた
    (ats030-0rte)。2回以上まわしたときは平均と幅を出し、幅を見ずに平均だけを
    比べないよう、出力に一行そえる。
    """
    source = Path("eval/run_eval.py").read_text(encoding="utf-8")
    assert '"--repeat", type=int, default=1' in source
    assert "def spread_of(summaries: list[dict], label: str, repeat: int)" in source
    assert '"mean":' in source and '"min":' in source and '"max":' in source
    assert "幅が重なっている差は、この評価では見えない差として扱うこと。" in source
    # 各回は別ファイルへ。混ざると、途中で上限に当たったとき引き継げない
    assert 'f"{label}-r{turn}"' in source
    # 既存の道具が1回ぶんの要約として読めるよう、平均は素の名前でも置く
    assert "**{key: metrics[key]['mean'] for key in metrics}" in source \
        or '**{key: metrics[key]["mean"] for key in metrics}' in source


def test_connecting_a_second_device_does_not_wipe_the_first():
    """つないだ直後の保存は、ドライブのファイルを丸ごと差し替える (PATCH)。

    別の端末でつなぐと、その端末のまだ空の記録で上書きされ、前の端末の記録が
    そこで消える。取り込みは統合なので、先に引いてから書けば両方残る。
    """
    settings = client.get("/assets/settings.js").text
    connect = settings.split('$("drive-connect").onclick')[1][:900]
    assert "loadFromDrive()" in connect and "saveToDrive()" in connect
    assert connect.index("loadFromDrive()") < connect.index("saveToDrive()")
    # 初めてつなぐ端末では、まだファイルが無い。それは失敗ではない
    assert "catch(error){" in connect


def test_the_drive_token_is_not_fetched_without_a_press():
    """GIS のトークン取得は必ずポップアップを開く。

    公式に "obtain a new token by calling requestAccessToken() from a user-driven
    event such as a button press" とある。読み込み時に呼ぶとブラウザに止められ、
    popup_failed_to_open になる。画面を移るたびにこれが起き、「すぐ切れる」ように
    見えていた。トークンはタブの中に持ち回し、取り直しは押されたときだけにする。
    """
    gdrive = client.get("/assets/gdrive.js").text
    assert "async function ensureDriveToken(clientId, {interactive = false} = {})" in gdrive
    assert "if (!interactive) {" in gdrive
    assert "const DRIVE_TOKEN_KEY" in gdrive and "sessionStorage.setItem(DRIVE_TOKEN_KEY" in gdrive
    # ディスクには残さない
    assert "localStorage.setItem(DRIVE_TOKEN_KEY" not in gdrive


def test_the_terms_describe_the_advertising_that_is_actually_shown():
    """広告を出しているのに「表示しません」と書いてあった。

    景品表示法の指定告示 (いわゆるステマ規制) は、広告を広告と分かる形で
    示すことを求める。アフィリエイトであることと、紹介料を受け取ることを
    規約に書く。Amazon アソシエイトの表示義務もここで満たす。
    """
    terms = client.get("/terms").text
    assert "無料公開ベータ版では広告を表示しません" not in terms
    assert "アフィリエイトリンク" in terms and "紹介料" in terms
    assert "Amazonのアソシエイトとして、生きものノートは適格販売により収入を得ています。" in terms
    assert "識別候補やその順位には一切影響しません" in terms
    # 広告のために利用者の中身を渡していない、と言い切る
    assert "写真、位置情報、判定結果をAmazonへ送信しません" in terms


def test_the_privacy_policy_names_the_right_processor():
    """Tailscale Funnel を止めて Cloud Run へ移ったのに、Tailscale が処理すると
    書いたままだった。接続情報の渡り先を誤って公表することになる。
    """
    privacy = client.get("/privacy").text
    assert "Tailscale" not in privacy
    assert "Google Cloud Run（東京リージョン）" in privacy
    assert "Google Cloud Firestore（東京リージョン）" in privacy


def test_the_newest_gemini_is_offered():
    """モデルは増える。古い一覧のままだと、利用者は新しいものを選べない。

    2026-08-14 に API の models.list を引いたところ gemini-3.7-flash が出ていた。
    同じ写真で試すと 3.6 Flash が 14.7秒、3.7 Flash は 8〜9秒で、動作も確認できた。
    """
    import config_store
    ids = [m["id"] for m in config_store.MODELS["gemini"]]
    assert "gemini-3.7-flash" in ids
    # 既定は据え置き。速さより無料枠の広さが要る (BYOK の利用者が自分で払う)
    assert config_store.DEFAULT_MODELS["gemini"] == "gemini-3.5-flash-lite"


def test_free_tier_numbers_are_not_asserted_in_the_labels():
    """Google はモデル別の無料枠の表を公開しなくなった (AI Studio でアカウントごと)。

    確かめられない数字を画面に書くと、古くなったまま断定し続けることになる。
    """
    import config_store
    labels = " ".join(m["label"] for m in config_store.MODELS["gemini"])
    assert "1日20回" not in labels
    assert "無料枠が広い" in labels        # 相対的な言い方は残す


def test_amazon_is_not_asked_again_while_it_keeps_refusing():
    """適格審査は日単位でしか変わらない。断られるたびに呼び直しても答えは同じ。

    本番のエラーログは /api/amazon/products の 503 で埋まり、ほかの異変が埋もれて
    いた。識別1回ごとに往復ぶんの待ち時間も乗る。断られたらしばらく呼ばない。
    """
    import main

    main._creators_pause_until = 0.0
    assert not main._creators_paused()
    main._pause_creators("AssociateNotEligible")
    assert main._creators_paused()

    source = Path("main.py").read_text(encoding="utf-8")
    # 資格・認証・混雑は待っても次の1回で直らない。5xx は一時的なので止めない
    assert "if exc.status in (401, 403, 429):" in source
    # 休んでいるあいだは 404。503 だと画面が赤字になる
    assert 'raise HTTPException(status_code=404, detail="商品APIはいま使えません")' in source
    main._creators_pause_until = 0.0


def test_the_entrance_says_what_the_app_is_before_asking_to_sign_in():
    """未ログインの人が見る唯一の画面。ここで何のアプリか分からなければ誰も入らない。

    以前は「預かるものは増えません」から始まっており、何ができるかも、自分の
    APIキーが要ることも書いていなかった。ログインして初めてキーが要ると知る形は、
    人を無駄に歩かせる。
    """
    page = client.get("/login").text
    assert "写真から、生きものの名前を調べます" in page
    assert "できること" in page
    # 要るものを、ログインボタンより前に出す
    assert "はじめるのに必要なもの" in page
    assert page.index("利用するAIの設定") < page.index('id="google-login"')
    assert "OllamaにはAPIキーは不要です" in page
    assert "写真を、写真を" not in page
    assert "Gemini には無料枠があります" in page
    # 検索や共有で出たときに、何のページか分かるようにする
    assert '<meta name="description"' in page
    assert "ログイン｜生きものノート" not in page      # 何のサイトか分からない題名


def test_the_entrance_still_warns_the_grown_ups():
    """全年齢のアプリなので、採る・触る・食べるの判断は大人が確かめる、を入口にも置く。"""
    page = client.get("/login").text
    assert "小学生以下のお子さんは大人といっしょに" in page
    assert "採る・触る・食べるの判断は、必ず大人が確かめてください" in page


def test_the_entrance_uses_styles_that_exist():
    """以前の入口は .wrap .lead .notes を使っていたが、どれも定義が無く素の見た目で出ていた。"""
    page = client.get("/login").text
    css = client.get("/assets/login.css").text
    import re
    used = set(re.findall(r'class="([^"]+)"', page))
    names = {c for group in used for c in group.split()}
    for name in names:
        assert f".{name}" in css, f"{name} に対応する定義が login.css に無い"


def test_the_public_pages_can_be_shared_and_found():
    """商用の基盤へ移した動機は「人に届くこと」だった。

    URL を貼っても素のリンクにしかならず、robots.txt はログインへ 303 で
    飛んでいてクローラが読めなかった。入口と文書だけを開ける。
    """
    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert robots.headers["content-type"].startswith("text/plain")
    assert "Allow: /login" in robots.text
    # 中の画面はログインが要る。辿らせても何も読めないので、叩かせない
    for closed in ("Disallow: /settings", "Disallow: /history", "Disallow: /api/"):
        assert closed in robots.text
    assert "Sitemap: " in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    # 表紙は / 。未ログインでも転送せずに入口が出る (所有権確認が転送を嫌う)
    assert "run.app/</loc>" in sitemap.text
    for path in ("/privacy", "/terms", "/changelog"):
        assert f"run.app{path}</loc>" in sitemap.text

    assert client.get("/ogp.png").status_code == 200


def test_every_public_page_has_a_sharing_card():
    """ログイン前に読める全ページを、貼られたときに何のページか分かるようにする。"""
    for path in ("/login", "/privacy", "/terms", "/changelog"):
        page = client.get(path).text
        for tag in ('property="og:title"', 'property="og:description"',
                    'property="og:image"', 'name="twitter:card"', 'name="description"'):
            assert tag in page, f"{path} に {tag} が無い"
        assert "/ogp.png" in page


def test_the_shelf_varies_without_asking_amazon_again():
    """開くたびに顔ぶれを変えたいが、そのたび問い合わせるのは筋が悪い。

    商品APIには秒あたりの上限があり、売上に応じてしか増えない。多めに取って
    覚えておき、どれを見せるかはブラウザ側で選ぶ。問い合わせは減り、並びは毎回
    変わる。LLM は一切増えない (問い合わせ語は識別済みの名前から作る)。
    """
    import main

    source = Path("main.py").read_text(encoding="utf-8")
    # 商品APIの上限まで貰う。見せる数ではなく、選択肢の数
    assert 'affiliate.get("partner_tag", ""), 10, index' in source
    assert "def _products_cached(" in source and "def _remember_products(" in source
    assert "_PRODUCT_TTL_SECONDS = 6 * 3600" in source
    # 価格は持たない。持っていれば24時間の制限がかかる
    creators = Path("creators_api.py").read_text(encoding="utf-8")
    assert '"title": title[:240], "url": url, "image": image' in creators
    assert '"price"' not in creators

    products = client.get("/assets/products.js").text
    assert "const SHELF_CARDS = 6;" in products
    # 受け取った時点で混ぜる。同じ切り口でも顔ぶれが変わる
    assert "for (const product of shuffle(Array.isArray(data.products) ? data.products : []))" in products
    # 問い合わせ語は識別結果から作る。LLM を呼び直さない
    assert "function productQueries(name, scientificName, category)" in products
    assert "fetch(\"/api/identify" not in products

    # 覚えたものは、休止中でも返す
    main._product_cache.clear()
    main._remember_products(("テスト", "All"), [{"title": "図鑑", "url": "u", "image": "i"}])
    assert main._products_cached(("テスト", "All"))[0]["title"] == "図鑑"
    main._product_cache.clear()


def test_six_cards_do_not_leave_a_ragged_row():
    """4列固定のままカードを6枚にすると、2行目が2つだけになる。"""
    for sheet in ("/assets/index.css", "/assets/history.css"):
        css = client.get(sheet).text
        assert "repeat(4,minmax(0,1fr))" not in css
        assert "repeat(auto-fill,minmax(132px,1fr))" in css


def test_the_click_count_survives_a_restart_in_production():
    """Cloud Run にディスクは無い。settings.json に足していたぶんは、インスタンスが
    入れ替わるたび 0 に戻っていた。数えていたつもりで何も残っていない。

    商品APIの資格 (直近30日で適格販売10件) までの距離を見るには、クリックが
    実際に起きているかどうかが要る。Firestore が使えるならそちらへ足す。
    """
    source = Path("auth.py").read_text(encoding="utf-8")
    assert "def bump_metric(field: str, amount: int = 1) -> None:" in source
    assert "def read_metrics() -> dict[str, int]:" in source
    # 読んで足して書くと、同時に押されたぶんが落ちる
    assert '"updateTransforms"' in source and '"increment"' in source
    assert "documents:commit" in source
    # 利用者の記録とは別の入れ物
    assert "/documents/metrics/" in source

    store = Path("config_store.py").read_text(encoding="utf-8")
    assert "if auth.using_firestore():" in store
    assert "auth.bump_metric(event)" in store
    assert "def affiliate_metrics() -> dict[str, int]:" in store
    # 数えられなくても広告そのものは出す
    assert "except Exception as error:      # 数えられなくても、広告そのものは出す" in store


def test_the_settings_screen_reads_whichever_store_is_in_use():
    """置き場が2通りあるので、読む側は1か所だけ見ればよい形にする。"""
    store = Path("config_store.py").read_text(encoding="utf-8")
    assert '"metrics": affiliate_metrics()' in store
    assert '"metrics": data["affiliate_metrics"]' not in store


def test_the_health_check_can_be_reached_from_outside():
    """死活の確認がログインの内側にあり、外からは 303 しか返らなかった。

    OPEN_PATHS には "/healthz" と書いてあったが、その名前のルートは無く 404。
    どちらの名前でも確かめられず、監視を掛けようがない状態だった。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert '"/health",' in source.split("OPEN_PATHS = {")[1][:400]
    assert '"/healthz"' not in source.split("OPEN_PATHS = {")[1][:400]
    body = client.get("/health")
    assert body.status_code == 200 and body.json()["ok"] is True
    # 公開版では中身を伏せる。動いているかを知るのにモデル名は要らない
    assert "if PUBLIC_MODE:\n        return {\"ok\": True}" in source


def test_the_front_page_does_not_bounce_anonymous_visitors():
    """公開サイトの表紙が /login なのは不自然で、所有権の確認も転送を挟むと通らない。

    未ログインの / は転送せず、そのまま入口を出す。ログイン済みの人はアプリが出る。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'if path == "/":' in source
    assert 'return _page("login.html")' in source
    # /login も残す。失敗の印つきで戻る先になっている
    assert '@app.get("/login", include_in_schema=False)' in source


def test_the_ownership_token_can_be_set_without_rebuilding():
    """確認 → 審査の往復を速くする。合言葉は環境変数で差せるようにしておく。"""
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'SITE_VERIFICATION = os.getenv("IKIMONO_SITE_VERIFICATION", "").strip()' in source
    assert "def _inject_site_verification(html: str) -> str:" in source
    assert 'return HTMLResponse(_inject_site_verification(html))' in source
    # ファイルを置けと言われる方式にも備える
    assert 'SITE_VERIFICATION_FILE = os.getenv("IKIMONO_SITE_VERIFICATION_FILE", "").strip()' in source
    assert 'return Response(f"google-site-verification: {SITE_VERIFICATION_FILE}"' in source
    # 設定していなければ何も差さない
    assert client.get("/login").text.count("google-site-verification") == 0
    assert client.get("/googleabc.html").status_code == 404


def test_the_entrance_describes_the_real_data_path():
    """識別はサーバー経由。ブラウザから直接ではない。

    /identify は request_api_key を受け取り、サーバーが事業者を呼ぶ。入口に
    「ブラウザから直接つなぎます」と書いていたが、これは事実と違った。
    データの流れを誤って公表することになる。
    """
    page = client.get("/login").text
    assert "ブラウザから直接つなぎます" not in page
    assert "サーバーへ送り、サーバーがあなたの選んだAIを呼びます" in page
    assert "写真は保存せず" in page
    # サーバーが受け取る作りであることを、実装の側でも確かめる
    source = Path("main.py").read_text(encoding="utf-8")
    assert "request_api_key" in source


def test_a_visitor_can_use_their_own_ollama_without_exposing_it():
    """公開版のサーバーに Ollama は無く、利用者の localhost にも届かない。

    利用者に Ollama をインターネットへ晒させるのは筋が悪く、サーバーが任意の
    URL へつなぐ形は SSRF の入り口になる。写真はブラウザから手元の Ollama へ
    直接渡し、サーバーは「何を訊くか」と「答えの仕上げ」だけを貸す。
    """
    ask = client.get("/api/local/prompt?location=日本&size=5cm")
    assert ask.status_code == 200
    body = ask.json()
    assert "撮影地域: 日本" in body["prompt"] and "大きさ: 5cm" in body["prompt"]
    # サーバーが Ollama を呼ぶときと同じ条件。揃えないと結果の傾向が変わる
    assert body["options"] == {"temperature": 0.1, "num_predict": 1200}
    assert body["format"] == "json" and body["think"] is False

    raw = ('{"category":"植物","candidates":[{"scientific_name":"Taraxacum officinale",'
           '"common_name_ja":"セイヨウタンポポ","confidence":70,"traits":["頭花が黄色"],'
           '"distinguishing_features":["総苞外片が反り返る"],"contradictions":[]}]}')
    done = client.post("/api/local/result", json={"text": raw, "model": "gemma4:12b"})
    assert done.status_code == 200
    assert done.json()["provider"] == "local"
    # 読めない答えは 422。500 にすると、利用者の側の問題が障害に見える
    assert client.post("/api/local/result", json={"text": "ただの文章"}).status_code == 422
    index = client.get("/assets/index.js").text
    assert "const cleaned = await shrinkForHistory(file);" in index
    assert "images.push(await fileToBase64(cleaned || file));" in index
    assert "LAN内のOllamaへ送ります" in index


def test_the_finishing_touches_live_in_one_place():
    """証拠ゲートと種の保存法の照合を JavaScript にも書くと、片方だけ直して食い違う。"""
    pipeline_source = Path("pipeline.py").read_text(encoding="utf-8")
    assert "def finish(result: dict[str, Any]) -> dict[str, Any]:" in pipeline_source
    assert "return finish(result)" in pipeline_source
    main_source = Path("main.py").read_text(encoding="utf-8")
    assert "return pipeline.finish(parsed)" in main_source
    index = client.get("/assets/index.js").text
    assert "async function identifyWithLocalOllama(files, context)" in index
    assert 'targetAddressSpace: "local"' in index
    assert "ローカルネットワークへのアクセス" in index
    assert 'saved.provider!=="local"||data.available_models.local.length||data.local_in_browser' in index
    # ブラウザは写真を渡して本文を受け取り、仕上げはサーバーへ預ける。
    # 注記を画面に描くのはブラウザの仕事だが、誰が保護種かを決めるのはサーバー
    assert '/api/local/prompt?' in index and '"/api/local/result"' in index
    assert "protected_species.json" not in index

    # 両方の経路が同じ仕上げを通る。サーバー経由の識別も、手元の Ollama も
    assert main_source.count("pipeline.finish(") == 1
    assert pipeline_source.count("def finish(") == 1


def test_the_browser_may_reach_a_local_ollama():
    """localhost はその端末の外へ出ない。ここを閉じたままだと接続できない。"""
    csp = client.get("/login").headers.get("content-security-policy", "")
    assert "http://localhost:11434" in csp and "http://127.0.0.1:11434" in csp
    assert "http://192.168.11.13:11434" in csp
    # 公開版でも選べる。以前は隠しており、手元で動かしている人まで選択肢を失っていた
    source = Path("main.py").read_text(encoding="utf-8")
    assert 'show_local = "1"' in source
    settings = client.get("/assets/settings.js").text
    assert "localRadio.disabled=!(localAvailable||data.local_in_browser);" in settings
    assert "localUrl:$(\"local-llm-url\").value.trim()" in settings
    assert "公開版では運営者が管理します" not in settings


def test_security_headers_survive_an_early_return():
    """途中の処理が早めに返すと、内側にある処理は動かない。

    ヘッダ付けを require_login より内側に置いていたため、ログインへの転送も、
    401 の応答も、未ログインのトップも CSP なしで出ていた。トップを直接返す
    ようにした時点で、表紙が丸ごと無防備になった。
    """
    source = Path("main.py").read_text(encoding="utf-8")
    # 最後に登録したものが一番外側で回る
    assert source.index("async def require_login") < source.index("async def security_headers")

    for path in ("/", "/login", "/privacy"):
        headers = client.get(path).headers
        assert "content-security-policy" in headers, f"{path} に CSP が無い"
        assert headers["x-content-type-options"] == "nosniff"

    # 転送と 401 にも付く
    import main
    original = main.PUBLIC_MODE
    try:
        main.PUBLIC_MODE = True
        blocked = client.get("/api/history-key")
        assert "content-security-policy" in blocked.headers
    finally:
        main.PUBLIC_MODE = original


def test_records_saved_on_another_device_arrive_when_you_come_back():
    """取り込みは1タブに1回だけだった。タブを開いたまま別の端末で足しても出てこない。

    かといって開くたび丸ごと引くのは重い (記録50件で数MB)。更新時刻だけ先に見て、
    新しくなければ何もしない。
    """
    drive = client.get("/assets/gdrive.js").text
    assert "async function pullIfDriveChanged(" in drive
    assert 'document.addEventListener("visibilitychange"' in drive
    # 中身を落とす前に更新時刻を見る
    assert "fields=modifiedTime" in drive
    assert 'if (!stamp || stamp === driveSeenAt()) return false;' in drive
    # 戻ってくるたびに叩かない
    assert "DRIVE_LOOK_INTERVAL" in drive
    # 自分が書いたぶんを「新しくなった」と数えない
    assert 'const fields = "&fields=id,modifiedTime";' in drive
    assert "rememberDriveSeen(written.modifiedTime" in drive
    # 押されていないので窓は開けない。生きているトークンがあるときだけ動く
    assert "if (!driveLinked() || !driveTokenAlive()) return false;" in drive


def test_public_analytics_waits_for_explicit_consent(monkeypatch):
    private_page = client.get("/login").text
    assert "/assets/analytics.js" not in private_page
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    public_page = client.get("/login")
    assert 'src="/assets/analytics.js" defer' in public_page.text
    assert 'href="/assets/analytics.css"' in public_page.text
    csp = public_page.headers["content-security-policy"]
    assert "https://www.googletagmanager.com" in csp
    assert "https://www.google-analytics.com" in csp
    script = client.get("/assets/analytics.js").text
    assert 'ANALYTICS_ID="G-T9FSRF5Q4F"' in script
    assert 'if(choice==="granted")loadAnalytics()' in script
    assert 'script.src="https://www.googletagmanager.com/gtag/js?id="' in script
    assert 'ad_storage:"denied"' in script
    assert "allow_google_signals:false" in script
    # パネルの居場所は CSS ファイルに預けない。analytics.css はファイル名で止められやすく、
    # 落ちると position:static に戻ってページ末尾へ流れ、押しても出ないように見える
    assert "PANEL_ANCHOR" in script and 'position:"fixed"' in script
    # Cookie通知フィルタに ##.analytics-consent という汎用ルールがあり、どのサイトでも
    # そのクラスを display:none にする。当たる名前を使うと、スクリプトもボタンも動いて
    # いるのにパネルだけ消え、外からは「押しても何も起きない」としか見えない
    assert 'panel.className="usage-choice"' in script
    # 見るのはクラス名としての使用だけ。localStorage のキー
    # (ikimono-analytics-consent) は CSS セレクタではないので当たらないし、
    # 変えると保存済みの選択が失われる
    assert 'className="analytics-consent"' not in script
    assert ".analytics-consent" not in client.get("/assets/analytics.css").text
    assert "Object.assign(panel.style,PANEL_ANCHOR)" in script
    assert "写真、位置情報、調べた結果は送りません" in script
    privacy = client.get("/privacy").text
    # 保持期間は GA4 側で2か月に設定済み。読み手が確かめようのない「管理画面で設定されます」
    # ではなく、実際に設定した値を書く
    assert "2か月保持したのち削除されます" in privacy
    # ボタンはスクリプトが置く。HTMLに直接書くと、解析を読み込まない側や、拡張機能に
    # このファイルを止められた画面に、押しても動かないボタンだけが残る
    assert 'id="analytics-reset"' not in privacy
    assert 'id="analytics-reset-slot"' in privacy
    assert "mountAnalyticsReset" in client.get("/assets/analytics.js").text
    assert "同意しない場合はGoogleのタグを読み込みません" in privacy


def test_result_and_history_sharing_use_one_safe_helper():
    sharing = client.get("/assets/sharing.js").text
    index = client.get("/assets/index.js").text
    history = client.get("/assets/history.js").text

    for path in ["/", "/history"]:
        assert '/assets/sharing.js' in page_source(path)
    assert index.count('class="btn x-share"') == 1
    assert history.count('class="btn x-share"') == 1
    assert 'if(!e.candidates?.length)return' in history
    assert 'function xShareUrl(candidates,pageUrl)' in sharing
    assert 'async function shareToX(candidates,photo,onError,onNotice,onShared)' in sharing
    assert 'fetch("/api/share",{method:"POST",body:form})' in sharing
    assert '"https://x.com/intent/tweet?"+params.toString()' in sharing
    assert 'class="btn x-share"' in index
    assert 'class="btn x-share"' in history
    assert 'id="sharePhotoX"' in index
    assert 'この結果だけの共有ページを作り、そのリンクをXへ送ります。' in index
    assert "widgets.js" not in page_source("/") + page_source("/history")
    assert 'pageUrl||location.origin+"/"' in sharing
    assert "結果は候補です。図鑑や実物で確かめてください。" in sharing
    # カードが出ない相手には本文しか残らない。アプリが名乗れるのはここだけ
    assert "「生きものノート」で調べました。" in sharing
    # 本文は識別結果の traits から組み立てる。AI を呼び直さないので共有時の通信は増えない
    assert "写真から見えた特徴：" in sharing
    assert "candidates?.[0]?.traits" in sharing
    assert "function xWeight(text)" in sharing and "X_WEIGHTED_LIMIT=280" in sharing
    assert "X_URL_WEIGHT=23" in sharing
    # 押した記録だけが公開ページになる。一覧や保存の経路から /api/share は呼ばない
    assert history.count('/api/share') == 0 and index.count('/api/share') == 0
    assert 'function deleteSharePage(token)' in sharing
    assert '公開を取り消す' in history
    # 取り消しの導線は公開ページ自体にもある。記録を消したあとや別の端末でも止められる
    revoke_script = client.get("/assets/share-page.js").text
    assert 'revokeShare' in revoke_script and '/api/share/' in revoke_script

    # 本文にも、公開ページへ送る中身にも、載せないと決めたものが混ざらないこと。
    # 範囲を切らずにファイル全体で見る。送る側が増えても、ここで気づける。
    # コメントは外す。理由を書いた文に禁止語が出るだけで落ちると、説明を削る方向へ働く
    # (summary_large_image は X のカード種別の名前で、識別結果の summary とは無関係)
    code_only = re.sub(r"/\*.*?\*/", "", sharing, flags=re.S)
    for private_field in [
        "thumbnail", "thumbnails", "coordinates", "observedDate", "userNote",
        "noteUpdatedAt", "summary", "provider", "model", "email", "api_key",
    ]:
        assert private_field not in code_only, private_field


def test_share_page_publishes_only_the_fields_we_chose(tmp_path, monkeypatch):
    """公開ページに出るのは写真・候補名・あてはまり度・特徴だけ。

    画面が何を送っても、載せる項目はサーバーが決める。ここを素通しにすると、画面側に
    項目が増えた日に、載せないと決めたもの (撮影地・観察メモ・要約) が公開ページへ回る。
    """
    monkeypatch.setattr(main.shares, "DB_PATH", tmp_path / "shares.db")
    candidates = [{
        "common_name_ja": "セイヨウタンポポ", "scientific_name": "Taraxacum officinale",
        "confidence": 60, "traits": ["ぎざぎざした根生葉"],
        # 画面が余計に送ってきた体で入れる。これらが出たら公開の約束が壊れている
        "summary": "キク科の草本と考えられます", "userNote": "自宅の庭で見つけた",
        "coordinates": {"latitude": 35.6812, "longitude": 139.7671},
        "observedDate": "2026-08-16", "provider": "gemini",
    }]
    created = client.post("/api/share",
                          files={"photo": ("a.jpg", usable_photo(), "image/jpeg")},
                          data={"candidates": json.dumps(candidates, ensure_ascii=False)})
    assert created.status_code == 200, created.text
    token = created.json()["token"]

    page = client.get(f"/s/{token}")
    assert page.status_code == 200
    assert "セイヨウタンポポ" in page.text and "ぎざぎざした根生葉" in page.text
    assert "あてはまり度 60%" in page.text
    for leaked in ["キク科の草本と考えられます", "自宅の庭で見つけた", "35.6812", "139.7671",
                   "2026-08-16", "gemini"]:
        assert leaked not in page.text, leaked
    # カードに要るタグ。robots の指示は置かない — noindex があると X はカードを
    # 作らず、画像もタイトルも取りに来ない。ここに noindex を足した版を配って、
    # 共有ページの唯一の用途を黙って壊したことがある
    assert 'property="og:image"' in page.text and 'name="twitter:card"' in page.text
    assert 'name="robots"' not in page.text
    assert "<meta name=\"robots\"" not in page.text
    assert client.get(f"/s/{token}/photo").status_code == 200


def test_share_can_be_revoked_and_stops_serving(tmp_path, monkeypatch):
    monkeypatch.setattr(main.shares, "DB_PATH", tmp_path / "shares.db")
    candidates = [{"common_name_ja": "セイヨウタンポポ", "confidence": 60, "traits": []}]
    token = client.post("/api/share",
                        files={"photo": ("a.jpg", usable_photo(), "image/jpeg")},
                        data={"candidates": json.dumps(candidates, ensure_ascii=False)}
                        ).json()["token"]
    assert client.get(f"/s/{token}").status_code == 200
    assert client.post(f"/api/share/{token}/delete").json() == {"deleted": True}
    # 取り消したら、ページも写真も出さない。カードの画像だけ生き残ると取り消しにならない
    assert client.get(f"/s/{token}").status_code == 404
    assert client.get(f"/s/{token}/photo").status_code == 404
    assert client.post(f"/api/share/{token}/delete").status_code == 404


def test_share_refuses_formats_x_cannot_show(tmp_path, monkeypatch):
    """webp は X のカードに出ない。受け取ってから画像の出ないページを作らない。"""
    monkeypatch.setattr(main.shares, "DB_PATH", tmp_path / "shares.db")
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "green").save(buffer, "WEBP")
    candidates = [{"common_name_ja": "セイヨウタンポポ", "confidence": 60, "traits": []}]
    refused = client.post("/api/share",
                          files={"photo": ("a.webp", buffer.getvalue(), "image/webp")},
                          data={"candidates": json.dumps(candidates, ensure_ascii=False)})
    assert refused.status_code == 415


def test_share_needs_a_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(main.shares, "DB_PATH", tmp_path / "shares.db")
    empty = client.post("/api/share",
                        files={"photo": ("a.jpg", usable_photo(), "image/jpeg")},
                        data={"candidates": "[]"})
    assert empty.status_code == 400
