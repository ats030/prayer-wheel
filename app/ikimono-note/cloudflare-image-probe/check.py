"""Verify image operations inside the local Workers runtime."""
import json
from urllib.request import urlopen

with urlopen("http://127.0.0.1:8790/health", timeout=60) as response:
    assert response.status == 200
    result = json.load(response)
assert result["ok"] is True
assert set(result["results"]) == {"JPEG", "PNG"}
for fmt, image in result["results"].items():
    assert image["size"] == [960, 1600], (fmt, image)
    assert image["original_date"] == "2026:10:07 12:34:56", (fmt, image)
    assert image["exif"] == 0 and image["bytes"] > 0, (fmt, image)
print("PASS: JPEG/PNG decode, EXIF date, orientation, resize, JPEG encode, EXIF removal")
