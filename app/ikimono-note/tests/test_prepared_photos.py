"""Browser-prepared route bounds, byte forwarding, and native-path isolation."""
import io
import json
from pathlib import Path
import sys

import httpx
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
import prepared_photos


@pytest.fixture
def anyio_backend():
    return "asyncio"


def jpeg(size=(600, 450), color="green", **kwargs):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "JPEG", **kwargs)
    return output.getvalue()


def reports(**measured):
    return json.dumps([{"metadata": {"observed_date": "2026-10-07", "latitude": 35.5,
                                    "longitude": 139.75},
                        "measured": {"width": 2000, "height": 1200, "pixels": 2400000,
                                     "brightness": 100, "contrast": 30, "sharpness": 49.9,
                                     **measured}}])


def test_jpeg_header_accepts_encoder_outputs_and_rejects_exif_size_and_truncation():
    for progressive in (False, True):
        assert prepared_photos.jpeg_dimensions(jpeg(progressive=progressive)) == (600, 450)
    exif = Image.Exif(); exif[306] = "2026:10:07 12:34:56"
    for raw in (jpeg(exif=exif), jpeg((1601, 300)), jpeg()[:-2], b"not-a-jpeg",
                b"x" * (prepared_photos.MAX_PREPARED_BYTES + 1)):
        with pytest.raises(main.vision.VisionError):
            prepared_photos.jpeg_dimensions(raw)


@pytest.mark.parametrize("serialized", ["", "{}", "[null]", "[]", reports(brightness=float("nan")),
                                         reports(contrast=float("inf")), reports(pixels=1),
                                         reports(width=True), reports(height=0), reports(sharpness=-1)])
def test_reports_reject_malformed_nonfinite_or_inconsistent_measurements(serialized):
    with pytest.raises(main.vision.VisionError):
        prepared_photos.read_reports(serialized, 1)


@pytest.mark.anyio
async def test_prepared_route_forwards_exact_bytes_and_context_without_decoding(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "BROWSER_PHOTOS", True)
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "BACKGROUND_JOBS", False)
    monkeypatch.setattr(main.auth, "configured", lambda: False)
    monkeypatch.setattr(main.config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    def forbidden(*args, **kwargs):
        raise AssertionError("Workers photo path must not decode pixels or call server Ollama")
    for name in ("prepare_image", "extract_exif_context"):
        monkeypatch.setattr(main.vision, name, forbidden)
    monkeypatch.setattr(main.image_quality, "judge", forbidden)
    monkeypatch.setattr(main.config_store, "ollama_models", forbidden)
    seen = []
    def identify(images, **context):
        seen.append((images, context))
        return {"candidates": [], "category": "不明"}
    monkeypatch.setattr(main.pipeline, "identify_all", identify)
    raw = jpeg()
    data = {"client_photos": reports(), "request_provider": "gemini",
            "request_model": main.config_store.MODELS["gemini"][0]["id"],
            "request_api_key": "synthetic-key", "location": "手入力の場所"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as client:
        settings = await client.get("/api/settings")
        assert settings.json()["browser_photos"] is True
        response = await client.post("/identify", data=data, files={"files": ("photo.jpg", raw, "image/jpeg")})
        assert response.status_code == 200, response.text
        assert seen[0][0] == [raw]
        assert seen[0][1]["location"] == "手入力の場所"
        assert seen[0][1]["observed_date"] == "2026-10-07"
        assert seen[0][1]["api_key"] == "synthetic-key"
        assert response.json()["photo_metadata"]["longitude"] == 139.75
        assert response.json()["photo_notes"][0]["reason"] == "blurry"
        assert not tmp_path.joinpath("settings.json").exists()
        data["client_photos"] = reports(brightness=14.9)
        blocked = await client.post("/identify", data=data, files={"files": ("photo.jpg", raw, "image/jpeg")})
        assert blocked.status_code == 422 and len(seen) == 1
        assert blocked.json()["detail"]["problems"][0]["reason"] == "dark"
        data.pop("client_photos")
        missing = await client.post("/identify", data=data, files={"files": ("photo.jpg", raw, "image/jpeg")})
        assert missing.status_code == 400 and len(seen) == 1
        assert (await client.post("/api/photo-original", content=b"not-a-zip")).status_code == 400


@pytest.mark.anyio
async def test_native_route_does_not_trust_client_measurements(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "BROWSER_PHOTOS", False)
    monkeypatch.setattr(main, "PUBLIC_MODE", False)
    monkeypatch.setattr(main, "BACKGROUND_JOBS", False)
    monkeypatch.setattr(main.config_store, "SETTINGS_PATH", tmp_path / "settings.json")
    def forbidden(*args, **kwargs):
        raise AssertionError("Dark native photo must not reach an AI provider")
    monkeypatch.setattr(main.pipeline, "identify_all", forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://localhost") as client:
        response = await client.post("/identify", data={"client_photos": reports(brightness=100)},
                                     files={"files": ("dark.jpg", jpeg(color="black"), "image/jpeg")})
        assert response.status_code == 422
