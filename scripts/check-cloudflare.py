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


def check(base, package='dist'):
    if urllib.parse.urlsplit(base).scheme != "https":
        raise ValueError("The published site must use HTTPS")
    base = base.rstrip("/")
    files = ["index.html", "app.js", "modern-translations.js", "player.js", "style.css", "data/sutra.json", "data/sutra-phrases.json", "favicon.png", "favicon.ico", "ads.txt"]
    files.extend("audition/" + name for name in ("index.html", "audition.css", "audition.js", "current.wav", "adjusted.wav", "chant.wav", "chant-female.wav"))
    manifest = json.loads((ROOT / "audio/manifest.json").read_text(encoding="utf-8"))
    files.extend("audio/" + entry["file"] for entry in manifest["files"])
    files.append('data/sutra-sections.json')
    files.append('drum-motion.js')
    files.extend(['character-scroll.js', 'data/character-timing.json'])
    character_cues = json.loads((ROOT / package / 'data/character-timing.json').read_text(encoding='utf-8'))
    files.extend('audio/' + s['file'] for s in character_cues['sections'])
    phrases = json.loads((ROOT / 'audio/phrases-manifest.json').read_text())
    files.extend('audio/' + entry['file'] for entry in phrases['files'])

    legacy = json.loads((ROOT / "audio/legacy-manifest.json").read_text())
    files.extend("audio/" + entry["file"] for entry in legacy["files"])

    def verify(name):
        path = "/" if name == "index.html" else "/audition/" if name == "audition/index.html" else "/" + name
        try:
            with fetch(base + path) as response:
                assert response.status == 200
                body = response.read()
                content_type = response.headers.get_content_type()
        except urllib.error.HTTPError as error:
            raise AssertionError(f'{name}: HTTP {error.code}') from error
        expected = (ROOT / package / name).read_bytes()
        assert hashlib.sha256(body).digest() == hashlib.sha256(expected).digest(), name
        if name.endswith(".wav"):
            assert content_type in ("audio/wav", "audio/wave", "audio/x-wav"), content_type
        elif name.endswith(".png"):
            assert content_type == "image/png", content_type
        elif name.endswith(".ico"):
            assert content_type in ("image/x-icon", "image/vnd.microsoft.icon"), content_type
        elif name.endswith(".js"):
            assert content_type in ("text/javascript", "application/javascript"), content_type
        elif name == "ads.txt":
            assert content_type == "text/plain", content_type
            assert body == b"google.com, pub-8787627445197940, DIRECT, f08c47fec0942fa0\n"
        elif name.endswith(".html"):
            assert content_type == "text/html"
            assert b"VOICEVOX:WhiteCUL" in body and b"ubuntu-server-app" not in body
            if name == "audition/index.html":
                assert b"VOICEVOX Nemo" in body
        return len(body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        size = sum(pool.map(verify, files))
    for private in ("pages/wrangler.jsonc", "scripts/build-pages.py", "docs/cloudflare-pages-license.yaml", "support-config.json", "scripts/support-link.py", "docs/support-license.yaml", "docs/support.md", "wrangler.jsonc", "README.md", "package.json", "data/character-readings.json", "scripts/character-timing.py", "audio/manifest.json", "audio/phrases-manifest.json", "audio/legacy-manifest.json", "audition/baseline/manifest.json", "audition/baseline/02.wav", "audition/baseline/sutra.json", "scripts/generate-recitation.py",
                    "assets/prayer-wheel-icon-source.png", "audition/manifest.json", "audition/chant-manifest.json", "audition/chant-female-manifest.json", "docs/chant-reference-analysis.json", "docs/chant-license.yaml", "scripts/generate-chant.py", "scripts/generate-audition.py", "scripts/generate-audio.py", "tests/player.test.js", "missing.wav"):
        try:
            with fetch(base + "/" + private):
                pass
        except urllib.error.HTTPError as error:
            assert error.code == 404, (private, error.code)
            if package == 'dist-pages':
                assert error.read() == (ROOT / package / '404.html').read_bytes(), private
        else:
            raise AssertionError("Unexpected public path: " + private)
    wav_count = sum(name.endswith(".wav") for name in files)
    print(f"HTTPS verified: {len(files)} exact assets, {size:,} bytes, all {wav_count} WAV hashes and MIME types match")
    print("Private configuration/source/metadata paths return 404; public HTML has no internal tracker")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://prayer-wheel.ats030.workers.dev")
    parser.add_argument('--package', choices=('dist', 'dist-pages'), default='dist')
    args = parser.parse_args()
    check(args.url, args.package)
