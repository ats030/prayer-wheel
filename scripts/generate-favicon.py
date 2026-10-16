#!/usr/bin/env python3
"""Draw an original eight-spoke Dharma wheel, supersampled for small tabs."""
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCALE = 8
image = Image.new('RGBA', (64 * SCALE, 64 * SCALE))
draw = ImageDraw.Draw(image)
gold = '#d7ad55'
ink = '#24211c'

def circle(radius, fill, width=0):
    box = tuple(int(v * SCALE) for v in (32-radius, 32-radius, 32+radius, 32+radius))
    draw.ellipse(box, fill=fill if not width else None,
                 outline=fill if width else None, width=int(width*SCALE) if width else 1)

circle(31, ink)
circle(26, gold, 4)
for spoke in range(8):
    angle = spoke * math.pi / 4
    points = [(int((32 + r * math.cos(angle))*SCALE),
               int((32 + r * math.sin(angle))*SCALE)) for r in (0, 30)]
    draw.line(points, fill=gold, width=3*SCALE)
circle(8, ink)
circle(7, gold, 3)
circle(2, gold)
image.resize((64, 64), Image.Resampling.LANCZOS).save(ROOT / 'favicon.png')
image.save(ROOT / 'favicon.ico', sizes=[(16,16), (32,32), (48,48), (64,64)])
print('Generated Dharma wheel PNG and ICO (16/32/48/64px)')
