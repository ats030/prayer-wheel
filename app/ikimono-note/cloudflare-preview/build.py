"""Reuse the checked allowlist builder with the real, protected entrypoint."""
import importlib.util
import hashlib
import json
import shutil
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
HERE = Path(globals().get("OUTPUT_DIR", SOURCE))
PROBE = HERE.parent / "cloudflare-app-probe"
spec = importlib.util.spec_from_file_location("probe_builder", PROBE / "build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
digest = builder.bundle_digest
builder.HERE = HERE
builder.bundle_digest = lambda manifest: hashlib.sha256(
    digest(manifest, "cloudflare-preview/src/worker.py").encode()
    + (HERE / "changelog.html").read_bytes()).hexdigest()
shutil.copyfile(PROBE / "manifest.json", HERE / "manifest.json")
builder.build()
# Private preview has its own truthful release note, without changing the old site.
resources = HERE / "src/_resources.py"
namespace = {}
exec(resources.read_text(), namespace)
namespace["RESOURCES"]["static/changelog.html"] = (HERE / "changelog.html").read_bytes()
# Static bytes stay inside the reviewed allowlist, but no longer cross the
# Python/ASGI response boundary. HTML and identification data remain embedded.
native = {name: raw for name, raw in namespace["RESOURCES"].items()
          if name.startswith(("static/assets/", "static/vendor/", "static/downloads/"))
          or name in {"static/theme.js", "static/favicon.png", "static/apple-touch-icon.png", "static/ogp.png"}}
source_names = set(json.loads((SOURCE / "sources.json").read_text())) | {"README.txt"}
allowed_assets = {name.removeprefix("static/") for name in native} | {
    "vendor/photo/sources/" + name for name in source_names}
assets = HERE / "assets"
if HERE != SOURCE:
    for name in source_names:
        source = SOURCE / "assets/vendor/photo/sources" / name
        target = assets / "vendor/photo/sources" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
for path in assets.rglob("*"):
    if path.is_symlink() or (path.is_file() and path.relative_to(assets).as_posix() not in allowed_assets):
        raise ValueError("Unexpected asset: " + path.relative_to(assets).as_posix())
for name, raw in native.items():
    path = assets / name.removeprefix("static/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    del namespace["RESOURCES"][name]
resources.write_text("BUNDLE_SHA256 = " + repr(namespace["BUNDLE_SHA256"]) + "\nRESOURCES = "
                     + repr(namespace["RESOURCES"]) + "\nNATIVE_ASSET_PATHS = "
                     + repr(frozenset("/" + name for name in sorted(allowed_assets)))
                     + "\nNATIVE_ASSET_LENGTHS = " + repr({
                         "/" + name: (assets / name).stat().st_size for name in sorted(allowed_assets)}) + "\n")
# Reuse already resolved, fixed dependencies, without a registry install.
for name in ("pyproject.toml", "pylock.toml"):
    shutil.copyfile(PROBE / name, HERE / name)
target = HERE / "python_modules"
if not target.exists():
    target.symlink_to(PROBE / "python_modules", target_is_directory=True)
