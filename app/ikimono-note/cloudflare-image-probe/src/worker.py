"""Synthetic JPEG/PNG compatibility probe; no HEIF or production imports."""
from io import BytesIO
from hashlib import sha256
from PIL import Image, ImageOps
from fastapi import FastAPI, Request
import time
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


@app.post("/measure")
async def measure(request: Request):
    # Optional imports keep the original health probe usable before preparation.
    import quality_reference
    import vision
    from reference_info import SOURCE_HASHES
    raw = await request.body()
    if len(raw) > vision.MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "oversized"}
    started = time.perf_counter()
    quality = quality_reference.judge(raw)
    judged = time.perf_counter()
    jpeg = vision.prepare_image(raw)
    prepared = time.perf_counter()
    return {"ok": True, "quality": quality, "source_hashes": SOURCE_HASHES,
            "jpeg_bytes": len(jpeg),
            "quality_wall_ms": round((judged-started)*1000, 3),
            "prepare_wall_ms": round((prepared-judged)*1000, 3)}


@app.post("/zip")
async def read_zip(request: Request):
    import photo_archive
    import vision
    raw = await request.body()
    started = time.perf_counter()
    try:
        photo, name, mime = photo_archive.read_original(raw)
        return {"ok": True, "name": name, "mime": mime, "bytes": len(photo),
                "sha256": sha256(photo).hexdigest(),
                "wall_ms": round((time.perf_counter()-started)*1000, 3)}
    except vision.VisionError as exc:
        return {"ok": False, "error": str(exc)}


Default = asgi.entrypoint(app)
