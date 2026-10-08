"""Generate synthetic HEIC fixtures and native Pillow reference results."""
import json
from hashlib import sha256
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from PIL.TiffImagePlugin import IFDRational
from pillow_heif import register_heif_opener

register_heif_opener()
directory = Path(__file__).resolve().parent / "fixtures"
directory.mkdir(exist_ok=True)
results = {}
for orientation, date_location in ([(value, "root") for value in range(1, 9)] + [(1, "ifd")]):
    image = Image.new("RGB", (2000, 1200), (80, 150, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 499, 299), fill=(220, 40, 40))
    draw.rectangle((1500, 0, 1999, 299), fill=(40, 40, 220))
    draw.rectangle((0, 900, 499, 1199), fill=(230, 200, 30))
    draw.rectangle((1500, 900, 1999, 1199), fill=(200, 30, 200))
    exif = Image.Exif()
    exif[274] = orientation
    if date_location == "root":
        exif[36867] = "2026:10:07 23:34:56"
    else:
        exif[34665] = {36867: "2026:10:07 23:34:56"}
    exif[34853] = {1: "N", 2: (IFDRational(35), IFDRational(30), IFDRational(0)),
                   3: "E", 4: (IFDRational(139), IFDRational(45), IFDRational(0))}
    name = f"orientation-{orientation}{'-exif-ifd' if date_location == 'ifd' else ''}.heic"
    # HEIF's encoder reads serialized EXIF to create irot/imir transforms.
    # Passing the Image.Exif object would silently leave out those transforms.
    image.save(directory / name, "HEIF", quality=90, exif=exif.tobytes())
    encoded = (directory / name).read_bytes()
    if orientation in (3, 5, 6, 7, 8):
        assert b"irot" in encoded, orientation
    if orientation in (2, 4, 5, 7):
        assert b"imir" in encoded, orientation
    with Image.open(directory / name) as decoded:
        metadata = decoded.getexif()
        transposed = ImageOps.exif_transpose(decoded).convert("RGB")
        width, height = transposed.size
        assert (width, height) == ((1200, 2000) if orientation >= 5 else (2000, 1200))
        results[name] = {
            "dimensions": [width, height],
            "observed_date": str(metadata.get(36867) or metadata.get_ifd(34665)[36867])[:10].replace(":", "-"),
            "latitude": 35.5, "longitude": 139.75,
            "corners": [list(transposed.getpixel(point)) for point in
                        ((50, 50), (width-51, 50), (50, height-51), (width-51, height-51))],
        }
# No EXIF is valid; missing metadata must not become invented date/GPS.
name = "without-exif.heic"
image = Image.new("RGB", (2000, 1200), (80, 150, 40))
image.save(directory / name, "HEIF", quality=90)
with Image.open(directory / name) as decoded:
    decoded.load()
    results[name] = {"dimensions": [2000, 1200], "context": {},
                     "corners": [list(decoded.getpixel((50,50)))] * 4}
(directory / "broken.heic").write_bytes((directory / "orientation-1.heic").read_bytes()[:32])
for method, label in ((zipfile.ZIP_STORED, "stored"), (zipfile.ZIP_DEFLATED, "deflated")):
    with zipfile.ZipFile(directory / f"{label}.zip", "w", method) as zipped:
        zipped.writestr("__MACOSX/._photo.heic", b"ignored metadata")
        zipped.writestr(".DS_Store", b"ignored metadata")
        zipped.writestr("photos/orientation-6.heic", (directory / "orientation-6.heic").read_bytes())
for label, names in (("multiple", ["a.heic", "b.heic"]), ("traversal", ["../photo.heic"])):
    with zipfile.ZipFile(directory / f"{label}.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in names:
            zipped.writestr(name, (directory / "orientation-6.heic").read_bytes())
# A stored archive with one changed payload byte proves CRC validation.
corrupt = bytearray((directory / "stored.zip").read_bytes())
needle = (directory / "orientation-6.heic").read_bytes()
index = corrupt.index(needle)
corrupt[index+40] ^= 1
(directory / "corrupt.zip").write_bytes(corrupt)
results["orientation-6.heic"]["sha256"] = sha256(needle).hexdigest()
(directory / "expected.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"Generated {len(results)} valid synthetic HEIC fixtures, one broken file and native references")
