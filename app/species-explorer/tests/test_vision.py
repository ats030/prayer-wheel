import io
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
import vision


def test_prepare_image_reencodes_and_resizes():
    source = io.BytesIO()
    Image.new("RGB", (2400, 1200), "green").save(source, "JPEG", exif=b"Exif\x00\x00test")
    result = vision.prepare_image(source.getvalue())
    image = Image.open(io.BytesIO(result))
    assert image.size == (1600, 800)
    assert not image.getexif()


def test_normalize_limits_candidates_and_confidence():
    data = {"category": "植物", "summary": "葉が写っています", "candidates": [
        {"common_name_ja": f"候補{i}", "confidence": 120, "traits": ["葉", "花", "茎", "余分"]}
        for i in range(4)
    ]}
    result = vision.normalize(data)
    assert len(result["candidates"]) == 3
    assert result["candidates"][0]["confidence"] == 100
    assert result["candidates"][0]["traits"] == ["葉", "花", "茎"]
    assert result["image_saved"] is False


def test_extract_json_accepts_fenced_output():
    assert vision._extract_json('```json\n{"category":"不明"}\n```')["category"] == "不明"


def test_identification_prompt_includes_supplied_context():
    prompt = vision.identification_prompt("東京都", "2026-08-09", "約5cm")
    assert "撮影地域: 東京都" in prompt
    assert "撮影日: 2026-08-09" in prompt
    assert "大きさ: 約5cm" in prompt
    assert "撮影地域: 東京都 不明" in vision.identification_prompt("東京都\n不明")



def test_taxonomy_verification_accepts_exact_scientific_name(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda name: [{"id": 123, "name": name}])
    result = vision.normalize({"category": "植物", "candidates": [{
        "common_name_ja": "タンポポ",
        "scientific_name": "Taraxacum officinale",
        "confidence": 82,
    }]})

    verified = vision.verify_taxonomy(result)

    assert verified["candidates"][0]["taxonomy_status"] == "verified"
    assert verified["candidates"][0]["taxonomy_url"].endswith("/123")
    assert verified["candidates"][0]["confidence"] == 82


def test_taxonomy_outage_keeps_candidate_and_confidence(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda name: None)
    result = vision.normalize({"category": "動物", "candidates": [{
        "common_name_ja": "候補", "scientific_name": "Known species", "confidence": 73
    }]})

    verified = vision.verify_taxonomy(result)

    assert verified["candidates"][0]["taxonomy_status"] == "unavailable"
    assert verified["candidates"][0]["confidence"] == 73


def test_taxonomy_verification_caps_unverified_name(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda name: [])
    result = vision.normalize({"category": "動物", "candidates": [{
        "common_name_ja": "架空種",
        "scientific_name": "Fictitious species",
        "confidence": 91,
    }]})

    verified = vision.verify_taxonomy(result)

    assert verified["candidates"][0]["taxonomy_status"] == "unverified"
    assert verified["candidates"][0]["confidence"] == 40


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://example.test")
        self.text = "provider-secret-body"

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "upstream error", request=self.request, response=self
            )


def test_openai_uses_responses_vision_contract(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse({"output": [{"content": [{
            "type": "output_text",
            "text": '{"category":"植物","summary":"葉","candidates":[]}',
        }]}]})

    monkeypatch.setattr(vision.httpx, "post", fake_post)
    result = vision.identify_openai(b"jpeg", "secret-openai")
    assert result["provider"] == "openai"
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["headers"]["Authorization"] == "Bearer secret-openai"
    content = seen["json"]["input"][0]["content"]
    assert content[0]["type"] == "input_image"
    assert content[1]["type"] == "input_text"



def test_plantnet_uses_multiple_images_and_parses_candidates(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse({
            "version": "test-model",
            "remainingIdentificationRequests": 499,
            "results": [{
                "score": 0.91,
                "species": {
                    "scientificNameWithoutAuthor": "Taraxacum officinale",
                    "commonNames": ["セイヨウタンポポ"],
                },
            }],
        })

    monkeypatch.setattr(vision.httpx, "post", fake_post)
    result = vision.identify_plantnet([b"one", b"two"], "plant-secret")

    assert seen["url"] == vision.PLANTNET_URL
    assert seen["params"]["api-key"] == "plant-secret"
    assert len(seen["files"]) == 2
    assert result["candidates"][0]["scientific_name"] == "Taraxacum officinale"
    assert result["candidates"][0]["confidence"] == 91
    assert result["remaining_requests"] == 499


def test_merge_plant_results_preserves_observed_traits():
    vlm = {
        "summary": "黄色い頭花", "model": "vision", "provider": "local",
        "candidates": [{
            "scientific_name": "Taraxacum officinale",
            "traits": ["黄色い頭花", "鋸歯のある葉"],
        }],
    }
    specialist = {
        "summary": "specialist", "model": "plant", "provider": "plantnet",
        "candidates": [{
            "scientific_name": "Taraxacum officinale",
            "traits": ["Pl植物画像識別による候補"],
        }],
    }

    result = vision.merge_plant_results(vlm, specialist)

    assert result["candidates"][0]["agreement"] == "matched"
    assert result["candidates"][0]["traits"][:2] == ["黄色い頭花", "鋸歯のある葉"]
    assert result["plantnet_used"] is True


def test_anthropic_uses_messages_vision_contract(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse({"content": [{
            "type": "text",
            "text": '{"category":"動物","summary":"羽","candidates":[]}',
        }]})

    monkeypatch.setattr(vision.httpx, "post", fake_post)
    result = vision.identify_anthropic(b"jpeg", "secret-anthropic")
    assert result["provider"] == "anthropic"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "secret-anthropic"
    image = seen["json"]["messages"][0]["content"][0]
    assert image["source"]["type"] == "base64"


def test_provider_error_does_not_expose_response_body():
    response = FakeResponse({}, 401)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        error = vision._provider_error("OpenAI", exc)
    assert "provider-secret-body" not in str(error)
    assert "APIキーを確認" in str(error)
