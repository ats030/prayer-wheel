"""Isolated local compatibility probe. No app data, keys, auth or AI calls."""
from io import BytesIO

from fastapi import FastAPI
from PIL import Image
from pillow_heif import register_heif_opener
from workers import asgi

register_heif_opener()
app = FastAPI()


@app.get("/health")
async def health():
    # Smallest useful image round-trip, not a CPU-budget or HEIC-decoding test.
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "green").save(buffer, "JPEG")
    with Image.open(BytesIO(buffer.getvalue())) as image:
        size = list(image.size)
    return {"ok": True, "jpeg_size": size, "heif_plugin_registered": True}


Default = asgi.entrypoint(app)
