"""Copy only image code and generate synthetic inputs; never import the app."""
import ast
from hashlib import sha256
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import zipfile
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
app = root.parent
quality = (app / "image_quality.py").read_bytes()
archive = (app / "photo_archive.py").read_bytes()
(root / "src/quality_reference.py").write_bytes(quality)
(root / "src/photo_archive.py").write_bytes(archive)
source = (app / "vision.py").read_text()
tree = ast.parse(source)
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "prepare_image")
isolated = ('import io\nfrom PIL import Image, ImageOps\n'
            'MAX_UPLOAD_BYTES = 15 * 1024 * 1024\nMAX_EDGE = 1600\n'
            'class VisionError(RuntimeError):\n    pass\n\n' + ast.get_source_segment(source, function) + '\n')
(root / "src/vision.py").write_text(isolated)
hashes = {"image_quality.py": sha256(quality).hexdigest(),
          "photo_archive.py": sha256(archive).hexdigest(),
          "prepare_image": sha256(isolated.encode()).hexdigest()}
(root / "src/reference_info.py").write_text(f"SOURCE_HASHES = {hashes!r}\n")
spec = importlib.util.spec_from_file_location("quality_reference", root / "src/quality_reference.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fixtures = root / "fixtures"
fixtures.mkdir(exist_ok=True)
expected = {"source_hashes": hashes, "photos": {}}
for name, size, fill in (("large", (2000, 1200), 120), ("small", (180, 120), 120),
                         ("dark", (2000, 1200), 4), ("sharp", (2000, 1200), 120)):
    image = Image.new("RGB", size, (fill, fill, fill))
    if name == "sharp":
        draw = ImageDraw.Draw(image)
        for y in range(0, size[1], 40):
            for x in range(0, size[0], 40):
                shade = 30 if (x//40+y//40) % 2 else 210
                draw.rectangle((x, y, x+39, y+39), fill=(shade, shade, shade))
    output = BytesIO()
    exif = Image.Exif()
    exif[36867] = "2026:10:07 23:34:56"
    image.save(output, "JPEG", quality=90, exif=exif)
    raw = output.getvalue()
    (fixtures / f"{name}.jpg").write_bytes(raw)
    expected["photos"][name] = module.judge(raw)
    with zipfile.ZipFile(fixtures / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(f"{name}.jpg", raw)
for name, entries in (("multiple", ["a.jpg", "b.jpg"]), ("traversal", ["../a.jpg"])):
    with zipfile.ZipFile(fixtures / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as zipped:
        for entry in entries:
            zipped.writestr(entry, (fixtures / "small.jpg").read_bytes())
(fixtures / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n")
print("Prepared isolated image code, source hashes, native quality references and synthetic ZIP fixtures")
