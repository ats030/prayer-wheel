#!/usr/bin/env python3
"""Package only the application's public assets for Cloudflare HTTPS hosting."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TAG = '<script src="http://ubuntu-server-app:8526/v.js" data-site="prayer-wheel" defer></script>'
reason = os.environ.get("VISIT_LOG_EXEMPT_REASON", "").strip()
if not reason:
    sys.exit("Set VISIT_LOG_EXEMPT_REASON for the documented public-network exception")
subprocess.run([sys.executable, str(ROOT / "scripts/check-audio.py")], check=True)
subprocess.run([sys.executable, str(ROOT / "scripts/check-audition.py")], check=True)
subprocess.run([sys.executable, str(ROOT / "scripts/check-chant.py")], check=True)
html = (ROOT / "index.html").read_text(encoding="utf-8")
if html.count(TAG) != 1:
    sys.exit("Expected exactly one self-hosted visit-log tag; update the exception explicitly")
public_html = html.replace("  " + TAG + "\n", "")
if "ubuntu-server-app" in public_html or "http://" in public_html:
    sys.exit("Public HTML still references internal or insecure resources")
out = ROOT / "dist"
if out.is_symlink():
    sys.exit("Refusing a symlink as the generated output directory")
if out.exists():
    shutil.rmtree(out)
out.mkdir()
(out / "index.html").write_text(public_html, encoding="utf-8")
for name in ("app.js", "player.js", "style.css", "favicon.png", "favicon.ico"):
    dest = out / name
    dest.parent.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / name, dest)
(out / "data").mkdir()
shutil.copyfile(ROOT / "data/sutra.json", out / "data/sutra-phrases.json")
shutil.copyfile(ROOT / "audition/baseline/sutra.json", out / "data/sutra.json")
(out / "audition").mkdir()
audition_html = (ROOT / "audition/index.html").read_text(encoding="utf-8")
if audition_html.count(TAG) != 1:
    sys.exit("Expected exactly one visit-log tag in audition HTML")
audition_html = audition_html.replace("  " + TAG + "\n", "")
if "ubuntu-server-app" in audition_html or "http://" in audition_html:
    sys.exit("Audition HTML references internal or insecure resources")
(out / "audition/index.html").write_text(audition_html, encoding="utf-8")
for name in ("audition.css", "audition.js", "current.wav", "adjusted.wav", "chant.wav", "chant-female.wav"):
    shutil.copyfile(ROOT / "audition" / name, out / "audition" / name)
manifest = json.loads((ROOT / "audio/manifest.json").read_text(encoding="utf-8"))
(out / "audio").mkdir()
for entry in manifest["files"]:
    target = out / "audio" / entry["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "audio" / entry["file"], target)
legacy = json.loads((ROOT / "audio/legacy-manifest.json").read_text())
for entry in legacy["files"]:
    shutil.copyfile(ROOT / "audio" / entry["file"], out / "audio" / entry["file"])
files = [p for p in out.rglob("*") if p.is_file()]
if len(files) != 15 + len(manifest["files"]) + len(legacy["files"]) or any(p.stat().st_size > 25 * 1024 * 1024 for p in files):
    sys.exit("Unexpected asset count or Cloudflare asset size limit exceeded")
print(f"Packaged {len(files)} public files ({sum(p.stat().st_size for p in files):,} bytes)")
print(f"VISIT_LOG_EXEMPT_REASON: {reason}")
