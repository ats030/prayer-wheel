#!/usr/bin/env python3
"""Validate the category colors in frontend/tokens.css.

Each --kind-* color must keep white cluster numbers readable (WCAG 4.5:1) and
stay distinguishable from every other category under normal vision and
simulated protanopia/deuteranopia (Machado et al. 2009, severity 1.0).
"""
import itertools
import math
import re
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parent.parent / 'frontend' / 'tokens.css'
MIN_CONTRAST = 4.5
MIN_DELTA_E = 10.0  # CIEDE2000; 5 dark hues under protanopia cannot all reach 12

SIMULATIONS = {
    'normal': None,
    'protan': ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    'deutan': ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
}


def kind_colors(text):
    return {name: value.lower() for name, value in re.findall(r'--kind-([a-z]+)\s*:\s*(#[0-9a-fA-F]{6})', text)}


def linear(hex_color):
    channels = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast_with_white(hex_color):
    return 1.05 / (luminance(linear(hex_color)) + 0.05)


def simulate(rgb, matrix):
    if matrix is None:
        return rgb
    return tuple(min(1.0, max(0.0, sum(m * c for m, c in zip(row, rgb)))) for row in matrix)


def lab(rgb):
    x = (0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]) / 0.95047
    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    z = (0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(lab1, lab2):
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c_bar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_bar ** 7 / (c_bar ** 7 + 25 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dlp, dcp = l2 - l1, c2p - c1p
    dhp = 0.0 if c1p * c2p == 0 else (h2p - h1p + 180) % 360 - 180
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lp_bar, cp_bar = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2
    else:
        hp_bar = (h1p + h2p + 360) / 2 % 360
    t = (1 - 0.17 * math.cos(math.radians(hp_bar - 30)) + 0.24 * math.cos(math.radians(2 * hp_bar))
         + 0.32 * math.cos(math.radians(3 * hp_bar + 6)) - 0.20 * math.cos(math.radians(4 * hp_bar - 63)))
    sl = 1 + 0.015 * (lp_bar - 50) ** 2 / math.sqrt(20 + (lp_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = (-2 * math.sqrt(cp_bar ** 7 / (cp_bar ** 7 + 25 ** 7))
          * math.sin(math.radians(60 * math.exp(-((hp_bar - 275) / 25) ** 2))))
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2 + rt * (dcp / sc) * (dHp / sh))


def check(colors):
    failures = []
    for name, value in colors.items():
        ratio = contrast_with_white(value)
        print(f'{name:10} {value}  white contrast {ratio:.2f}')
        if ratio < MIN_CONTRAST:
            failures.append(f'{name} {value}: white contrast {ratio:.2f} < {MIN_CONTRAST}')
    for vision, matrix in SIMULATIONS.items():
        labs = {name: lab(simulate(linear(value), matrix)) for name, value in colors.items()}
        closest = min(itertools.combinations(labs, 2), key=lambda pair: ciede2000(labs[pair[0]], labs[pair[1]]))
        for a, b in itertools.combinations(labs, 2):
            delta = ciede2000(labs[a], labs[b])
            if delta < MIN_DELTA_E:
                failures.append(f'{vision}: {a}/{b} deltaE {delta:.1f} < {MIN_DELTA_E}')
        print(f'{vision:10} closest {closest[0]}/{closest[1]} deltaE {ciede2000(labs[closest[0]], labs[closest[1]]):.1f}')
    return failures


def main():
    colors = kind_colors(TOKENS.read_text(encoding='utf-8'))
    expected = {'shiseki', 'omatsuri', 'onsen', 'tokusan', 'geo'}
    if set(colors) != expected:
        sys.exit(f'tokens.css must define --kind-* for exactly {sorted(expected)}; found {sorted(colors)}')
    failures = check(colors)
    for failure in failures:
        print('FAIL', failure)
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
