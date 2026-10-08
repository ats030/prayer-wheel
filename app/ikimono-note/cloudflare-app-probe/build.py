"""Assemble only reviewed modules and resources; never copy settings or .env."""
import json
import hashlib
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
APP = HERE.parent
VENDOR = {
    "static/vendor/photo/libheif.mjs": "libheif-js/libheif-wasm/libheif-bundle.mjs",
    "static/vendor/photo/exifr.mjs": "exifr/dist/full.esm.mjs",
    "static/vendor/photo/LIBHEIF-LICENSE.txt": "libheif-js/libheif-wasm/LICENSE",
    "static/vendor/photo/EXIFR-LICENSE.txt": "exifr/LICENSE",
}


def vendor_resources():
    root = APP / "cloudflare-browser-photo-probe" / "node_modules"
    for package, version in (("libheif-js", "1.23.5"), ("exifr", "7.1.3")):
        if json.loads((root / package / "package.json").read_text())["version"] != version:
            raise ValueError(f"Unexpected {package} version")
    return {name: (root / source).read_bytes() for name, source in VENDOR.items()}


def bundle_digest(manifest):
    digest = hashlib.sha256()
    for name in ["cloudflare-app-probe/src/worker.py", *manifest["modules"], *manifest["resources"]]:
        content = (APP / name).read_bytes()
        digest.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    for name, content in vendor_resources().items():
        digest.update(name.encode() + b"\0" + str(len(content)).encode() + b"\0" + content)
    return digest.hexdigest()


def build():
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name in manifest["modules"] + manifest["resources"]:
        path = APP / name
        if Path(name).is_absolute() or any(part in {".", ".."} or part.startswith(".")
                                         for part in Path(name).parts):
            raise ValueError(f"Invalid resource name: {name}")
        if path.is_symlink() or not path.resolve().is_relative_to(APP.resolve()):
            raise ValueError(f"Resource escapes application: {name}")
        if name.startswith("static/") or name == "data/protected_species.json":
            continue
        if "/" in name or not name.endswith(".py"):
            raise ValueError(f"Invalid module: {name}")
    target = HERE / "src"
    target.mkdir(exist_ok=True)
    allowed = {"worker.py", "_resources.py", *manifest["modules"]}
    unexpected = [p.name for p in target.iterdir() if p.is_symlink() or not p.is_file() or p.name not in allowed]
    if unexpected:
        raise ValueError(f"Unexpected files in Worker bundle: {unexpected}")
    for name in manifest["modules"]:
        shutil.copyfile(APP / name, target / name)
    resources = {name: (APP / name).read_bytes() for name in manifest["resources"]}
    resources.update(vendor_resources())
    (target / "_resources.py").write_text(
        "BUNDLE_SHA256 = " + repr(bundle_digest(manifest)) + "\nRESOURCES = " + repr(resources) + "\n")
    print(f"Assembled {len(manifest['modules'])} modules and {len(resources)} resources")


if __name__ == "__main__":
    build()
