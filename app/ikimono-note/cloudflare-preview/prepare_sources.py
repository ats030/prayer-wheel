"""Provide exact corresponding sources alongside the browser library."""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
TARGET = HERE / "assets/vendor/photo/sources"
SOURCES = {
    "libheif-js.tar.gz": "https://codeload.github.com/catdad-experiments/libheif-js/tar.gz/d8ec4bc3bc5bf8055975577bccbbc7e1d7313c2d",
    "libheif-emscripten.tar.gz": "https://codeload.github.com/catdad-experiments/libheif-emscripten/tar.gz/5c8968a44e9c68ae677e24790d77d001ed7fe7cc",
    "libheif.tar.gz": "https://codeload.github.com/strukturag/libheif/tar.gz/413e2a87e6a70b3eccc3a3adc5801179dd2d9e00",
    "libde265.tar.gz": "https://github.com/strukturag/libde265/releases/download/v1.0.15/libde265-1.0.15.tar.gz",
}

def prepare():
    TARGET.mkdir(parents=True, exist_ok=True)
    lockfile = HERE / "sources.json"
    locked = json.loads(lockfile.read_text()) if lockfile.exists() else {}
    records = {}
    for name, url in SOURCES.items():
        path = TARGET / name
        if not path.exists():
            with urlopen(url, timeout=60) as response:
                raw = response.read(24 * 1024 * 1024 + 1)
            if len(raw) > 24 * 1024 * 1024 or not raw.startswith(b"\x1f\x8b"):
                raise ValueError(f"Invalid source archive: {name}")
            path.write_bytes(raw)
        record = {"url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if name in locked and record != locked[name]:
            raise ValueError(f"Changed source archive: {name}")
        records[name] = record
    lockfile.write_text(json.dumps(records, indent=2) + "\n")
    (TARGET / "README.txt").write_text(
        "libheif-js 1.23.5: unmodified browser library, LGPL-3.0.\n"
        "Corresponding sources and build instructions: all four archives here.\n"
        "Use libheif-emscripten workflow with libheif sources placed at libheif/.\n"
        "The build uses Emscripten 3.1.61 and libde265 1.0.15.\n"
        "Then use libheif-js scripts/install.js and scripts/bundle.js.\n"
        "GNU LGPL/GPL notices: ../LIBHEIF-LICENSE.txt.\n"
        "You may replace /vendor/photo/libheif.mjs with a modified build;\n"
        "the application imports its public API and imposes no integrity check.\n")
    print("Prepared four corresponding-source archives and replacement instructions")

if __name__ == "__main__":
    prepare()
