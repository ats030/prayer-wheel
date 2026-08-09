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


def test_extract_exif_context_reads_capture_date():
    source = io.BytesIO()
    exif = Image.Exif()
    exif[36867] = "2025:04:03 12:34:56"
    Image.new("RGB", (2, 2), "green").save(source, "JPEG", exif=exif)

    assert vision.extract_exif_context(source.getvalue()) == {
        "observed_date": "2025-04-03",
    }


def test_gps_coordinate_converts_and_applies_direction():
    assert vision._gps_coordinate((35, 30, 0), "N") == 35.5
    assert vision._gps_coordinate((139, 45, 0), b"W") == -139.75
    assert vision._gps_coordinate(None, "N") is None


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


def test_gemini_prompt_requires_observation_comparison_and_abstention():
    prompt = vision.gemini_identification_prompt()
    assert "種名を考える前" in prompt
    assert "主要な類似種" in prompt
    assert "候補は棄却" in prompt
    assert "属・科レベル" in prompt
    assert "候補なし" in prompt



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
    assert result["candidates"][0]["common_name_ja"] == "セイヨウタンポポ"
    assert result["candidates"][0]["confidence"] == 91
    assert result["remaining_requests"] == 499


def test_plantnet_does_not_present_foreign_common_name_as_japanese(monkeypatch):
    monkeypatch.setattr(vision.httpx, "post", lambda *args, **kwargs: FakeResponse({
        "results": [{"score": 0.8, "species": {
            "scientificNameWithoutAuthor": "Taraxacum officinale",
            "commonNames": ["Common dandelion"],
        }}],
    }))
    result = vision.identify_plantnet(b"image", "key")
    assert result["candidates"][0]["common_name_ja"] == "和名未登録"


def test_taxonomy_does_not_present_foreign_preferred_name_as_japanese(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda _name: [{
        "id": 1, "name": "Taraxacum officinale", "preferred_common_name": "Common dandelion",
    }])
    result = vision.apply_evidence_gate({
        "provider": "local", "candidates": [{
            "common_name_ja": "生成和名", "scientific_name": "Taraxacum officinale", "confidence": 70,
        }],
    })
    assert result["candidates"][0]["common_name_ja"] == "和名未登録"


def test_merge_plant_results_does_not_promote_vlm_traits_as_facts():
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
            "traits": ["Pl@ntNet植物画像識別による候補"],
        }],
    }

    result = vision.merge_plant_results(vlm, specialist)

    assert result["candidates"][0]["agreement"] == "matched"
    assert result["candidates"][0]["traits"] == ["Pl@ntNet植物画像識別による候補"]
    assert result["summary"] == "specialist"
    assert result["plantnet_used"] is True


def test_evidence_gate_rejects_unverified_vlm_candidate(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda _name: [])
    result = vision.apply_evidence_gate({
        "provider": "local", "summary": "generated", "candidates": [{
            "common_name_ja": "架空種", "scientific_name": "Inventus species",
            "confidence": 92, "traits": ["生成された特徴"], "uncertainty": "",
        }],
    })
    assert result["candidates"] == []
    assert result["rejected_candidates"] == 1
    assert result["strict_mode"] is True


def test_evidence_gate_keeps_exact_taxon_but_marks_image_match_unverified(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda _name: [{
        "id": 47126, "name": "Taraxacum officinale", "preferred_common_name": "セイヨウタンポポ",
    }])
    result = vision.apply_evidence_gate({
        "provider": "local", "summary": "generated", "candidates": [{
            "common_name_ja": "誤った和名", "scientific_name": "Taraxacum officinale",
            "confidence": 92, "traits": ["生成された特徴"], "uncertainty": "",
        }],
    })
    candidate = result["candidates"][0]
    assert candidate["common_name_ja"] == "セイヨウタンポポ"
    assert candidate["evidence_status"] == "taxonomy_only"
    assert candidate["confidence"] == 40
    assert candidate["traits"] == []
    assert "写真との一致は未検証" in candidate["uncertainty"]


def test_evidence_gate_rejects_vlm_candidate_when_taxonomy_is_unavailable(monkeypatch):
    monkeypatch.setattr(vision, "_lookup_taxon", lambda _name: None)
    result = vision.apply_evidence_gate({
        "provider": "anthropic", "summary": "", "candidates": [{
            "common_name_ja": "候補", "scientific_name": "Known species", "confidence": 70,
        }],
    })
    assert result["candidates"] == []


def test_evidence_gate_marks_independent_plantnet_agreement():
    result = vision.apply_evidence_gate({
        "provider": "plantnet", "summary": "specialist", "candidates": [
            {"scientific_name": "A", "agreement": "matched"},
            {"scientific_name": "B", "agreement": "specialist_only"},
        ],
    })
    assert [c["evidence_status"] for c in result["candidates"]] == ["corroborated", "specialist_only"]


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


def test_gemini_uses_generate_content_vision_contract(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return FakeResponse({"candidates": [{"content": {"parts": [{
            "text": '{"category":"植物","summary":"葉","candidates":[]}',
        }]}}]})

    monkeypatch.setattr(vision.httpx, "post", fake_post)
    result = vision.identify_gemini([b"one", b"two"], "secret-gemini", "gemini-3.6-flash")
    assert result["provider"] == "gemini"
    assert seen["url"].endswith("/models/gemini-3.6-flash:generateContent")
    assert seen["headers"]["x-goog-api-key"] == "secret-gemini"
    parts = seen["json"]["contents"][0]["parts"]
    assert [part["inline_data"]["data"] for part in parts[:2]] == ["b25l", "dHdv"]
    assert parts[2]["text"]
    assert seen["json"]["generationConfig"]["responseMimeType"] == "application/json"
    config = seen["json"]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "high"}
    assert config["responseSchema"]["properties"]["candidates"]["maxItems"] == 3
    assert config["responseSchema"]["properties"]["category"]["enum"] == ["植物", "動物", "不明"]
