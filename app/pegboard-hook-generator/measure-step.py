#!/usr/bin/env python3
"""STEP の CARTESIAN_POINT から外形寸法を出す (ats030-y9fb.2)。

CAD カーネルは要らない。STEP はテキストなので座標を直接読める。角柱的な部品では
制御点が外形と一致するため、これで寸法規則を割り出せる (ats030-y9fb.6 で角度に
同じ手法を使った)。
"""
import re
import sys
from pathlib import Path

ROOT = Path("/home/ats030/pCloudDrive/CAD/PrintableFiles")
PAT = re.compile(r"CARTESIAN_POINT\('[^']*',\(([-0-9.E+]+),([-0-9.E+]+),([-0-9.E+]+)\)\)")


def bbox(path: Path):
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    n = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in PAT.finditer(line):
                n += 1
                for k in range(3):
                    v = float(m.group(k + 1))
                    lo[k] = min(lo[k], v)
                    hi[k] = max(hi[k], v)
    if not n:
        return None
    return [hi[k] - lo[k] for k in range(3)], n


def main(patterns):
    for pat in patterns:
        print(f"=== {pat} ===")
        dirs = sorted(ROOT.glob(pat))
        for d in dirs:
            step = next(iter(d.glob("*.step")), None)
            if not step:
                continue
            r = bbox(step)
            if not r:
                print(f"  {d.name:<20} 座標が読めない")
                continue
            (dx, dy, dz), n = r
            print(f"  {d.name:<20} X {dx:6.1f} / Y {dy:6.1f} / Z {dz:6.1f}  (点 {n})")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["BarHolder-D4-*", "S-Hook_*", "Hook-1-*"])
