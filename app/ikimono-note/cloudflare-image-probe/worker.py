"""Synthetic JPEG/PNG compatibility probe; no HEIF or production imports."""
from io import BytesIO
from PIL import Image, ImageOps
from fastapi import FastAPI
from workers import asgi

app = FastAPI()


@app.get("/health")
async def health():
    results = {}
    for fmt in ("JPEG", "PNG"):
        buffer = BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        exif[36867] = "2026:10:07 12:34:56"
        Image.new("RGB", (2000, 1200), (80, 150, 40)).save(buffer, fmt, exif=exif)
        with Image.open(BytesIO(buffer.getvalue())) as source:
            original_date = source.getexif().get(36867)
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1600, 1600))
            output = BytesIO()
            image.save(output, "JPEG", quality=90)
        with Image.open(BytesIO(output.getvalue())) as decoded:
            results[fmt] = {"size": list(decoded.size), "exif": len(decoded.getexif()),
                            "bytes": len(output.getvalue()), "original_date": original_date}
    return {"ok": True, "results": results}


Default = asgi.entrypoint(app)
