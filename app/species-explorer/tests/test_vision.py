import io
import sys
from pathlib import Path

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
