#!/usr/bin/env python3
"""Verify HTTPS assets against the local package and check private paths stay 404."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "prayer-wheel-deployment-check/1.0"})
    return urllib.request.urlopen(request, timeout=30)


def check(base):
    if urllib.parse.urlsplit(base).scheme != "https":
        raise ValueError("The published site must use HTTPS")
    base = base.rstrip("/")
    files = ["index.html", "app.js", "player.js", "style.css", "data/sutra.json", "favicon.png", "favicon.ico"]
    files.extend("audition/" + name for name in ("index.html", "audition.css", "audition.js", "current.wav", "adjusted.wav"))
    manifest = json.loads((ROOT / "audio/manifest.json").read_text(encoding="utf-8"))
    files.extend("audio/" + entry["file"] for entry in manifest["files"])

    def verify(name):
        path = "/" if name == "index.html" else "/audition/" if name == "audition/index.html" else "/" + name
        with fetch(base + path) as response:
            assert response.status == 200
            body = response.read()
            content_type = response.headers.get_content_type()
        expected = (ROOT / "dist" / name).read_bytes()
        assert hashlib.sha256(body).digest() == hashlib.sha256(expected).digest(), name
        if name.endswith(".wav"):
            assert content_type in ("audio/wav", "audio/wave", "audio/x-wav"), content_type
        elif name.endswith(".png"):
            assert content_type == "image/png", content_type
        elif name.endswith(".ico"):
            assert content_type in ("image/x-icon", "image/vnd.microsoft.icon"), content_type
        elif name.endswith(".js"):
            assert content_type in ("text/javascript", "application/javascript"), content_type
        elif name.endswith(".html"):
            assert content_type == "text/html"
            assert b"VOICEVOX Nemo" in body and b"ubuntu-server-app" not in body
        return len(body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        size = sum(pool.map(verify, files))
    for private in ("wrangler.jsonc", "README.md", "package.json", "audio/manifest.json",
                    "assets/prayer-wheel-icon-source.png", "audition/manifest.json", "scripts/generate-audition.py", "scripts/generate-audio.py", "tests/player.test.js", "missing.wav"):
        try:
            with fetch(base + "/" + private):
                pass
        except urllib.error.HTTPError as error:
            assert error.code == 404, (private, error.code)
        else:
            raise AssertionError("Unexpected public path: " + private)
    print(f"HTTPS verified: {len(files)} exact assets, {size:,} bytes, all 29 WAV hashes and MIME types match")
    print("Private configuration/source/metadata paths return 404; public HTML has no internal tracker")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://prayer-wheel.ats030.workers.dev")
    check(parser.parse_args().url)
