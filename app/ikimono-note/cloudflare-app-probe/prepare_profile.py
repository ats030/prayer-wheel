"""Generate only a reproducible, synthetic detailed JPEG. Never read real photos."""
import io
import random
from pathlib import Path
from PIL import Image

output = Path(__file__).resolve().parent / "profile-fixtures"
output.mkdir(exist_ok=True)
image = Image.frombytes("RGB", (1600, 1600), random.Random(3).randbytes(1600 * 1600 * 3))
encoded = io.BytesIO()
image.save(encoded, format="JPEG", quality=86)
raw = encoded.getvalue()
assert len(raw) <= 2 * 1024 * 1024
(output / "noise.jpg").write_bytes(raw)
print(f"Synthetic 1600x1600 JPEG: {len(raw)} bytes")
