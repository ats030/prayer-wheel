"""Reuse the checked allowlist builder with the real, protected entrypoint."""
import importlib.util
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
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
resources.write_text("BUNDLE_SHA256 = " + repr(namespace["BUNDLE_SHA256"]) + "\nRESOURCES = "
                     + repr(namespace["RESOURCES"]) + "\n")
# Reuse already resolved, fixed dependencies, without a registry install.
for name in ("pyproject.toml", "pylock.toml"):
    shutil.copyfile(PROBE / name, HERE / name)
target = HERE / "python_modules"
if not target.exists():
    target.symlink_to(PROBE / "python_modules", target_is_directory=True)
