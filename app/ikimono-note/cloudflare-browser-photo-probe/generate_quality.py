"""Synthetic quality corpus; expected results come from the production module."""
import io
import json
import sys
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from image_quality import judge

directory = Path(__file__).resolve().parent / "fixtures"
directory.mkdir(exist_ok=True)
results = {}

def save(name, image):
    data = io.BytesIO()
    image.save(data, "PNG")
    (directory / name).write_bytes(data.getvalue())
    result = judge(data.getvalue())
    result["problems"] = [{"level": p["level"], "reason": p["reason"]} for p in result["problems"]]
    results[name] = result

for edge in (1, 199, 200, 299, 300, 320, 1200):
    image = Image.new("RGB", (edge * 2, edge), (80, 150, 40))
    draw = ImageDraw.Draw(image)
    for x in range(0, image.width, 9):
        draw.rectangle((x, 0, x+3, edge-1), fill=(230, 80, 190))
    save(f"quality-edge-{edge}.png", image)
    if edge == 1200:
        for radius in (1, 2, 4, 8, 16):
            save(f"quality-blur-{radius}.png", image.filter(ImageFilter.GaussianBlur(radius)))
for brightness in (0, 14, 15, 24, 25, 255):
    save(f"quality-brightness-{brightness}.png", Image.new("RGB", (600, 400), (brightness,)*3))
for base in (14, 24):
    image = Image.new("RGB", (600, 400), (base+1,)*3)
    ImageDraw.Draw(image).rectangle((0, 0, 29, 399), fill=(base,)*3)
    save(f"quality-brightness-round-{base}.png", image)
for amplitude in (9, 10, 11):
    image = Image.new("RGB", (400, 400), (100-amplitude,)*3)
    ImageDraw.Draw(image).rectangle((200, 0, 399, 399), fill=(100+amplitude,)*3)
    save(f"quality-contrast-{amplitude}.png", image)
# Seeded texture and progressive blur exercise the sharpness threshold rather
# than comparing only obvious good/bad cases.
rng = random.Random(42)
texture = Image.frombytes("RGB", (800, 600), bytes(rng.randrange(256) for _ in range(800*600*3)))
for step in range(31):
    save(f"quality-texture-blur-{step}.png", texture.filter(ImageFilter.GaussianBlur(step / 10)))
(directory / "quality-expected.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"Generated {len(results)} synthetic quality references")
