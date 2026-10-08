"""Check the protected real app without user data or external AI requests."""
import base64
import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
STATE = Path('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json')

def check(origin):
    password = json.loads(STATE.read_text())["IKIMONO_PREVIEW_PASSWORD"]
    credential = "Basic " + base64.b64encode(("preview:" + password).encode()).decode()
    def fetch(path, authenticated=True, method="GET", body=None, extra=None):
        headers = {"Authorization": credential} if authenticated else {}
        headers["User-Agent"] = "ikimono-note-deployment-check/1.0"
        headers.update(extra or {})
        try:
            response = urlopen(Request(origin + path, data=body, method=method, headers=headers), timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    for path in ("/", "/health", "/assets/index.js", "/vendor/photo/libheif.mjs",
                 "/vendor/photo/sources/libheif.tar.gz", "/api/settings", "/probe/profile/native-health"):
        status, body, headers = fetch(path, False)
        assert status == 401, (path, status, body[:200])
        assert headers["Cache-Control"] == "no-store"
        assert "noindex" in headers["X-Robots-Tag"]
    status, _, _ = fetch("/health", extra={"Authorization": "Basic invalid"})
    assert status == 401
    namespace = {}
    exec((HERE / "src/_resources.py").read_text(), namespace)
    status, body, headers = fetch("/health")
    assert status == 200, (status, body[:100])
    assert headers["X-Preview-Bundle-SHA256"] == namespace["BUNDLE_SHA256"]
    assert "noindex" in headers["X-Robots-Tag"]
    for path in ("/", "/settings", "/history", "/changelog", "/assets/index.js", "/vendor/photo/libheif.mjs"):
        status, body, headers = fetch(path)
        assert status == 200, (path, status, body[:100])
        assert headers["Cache-Control"] == "no-store"
    assert "Cloudflare検証版" in fetch("/changelog")[1].decode()
    for path in ("/probe/profile/native-health", "/.env", "/src/worker.py", "/secrets.json"):
        assert fetch(path)[0] == 404, path
    settings = json.loads(fetch("/api/settings")[1])
    assert settings.get("browser_photos") is True, settings.keys()
    assert settings.get("google_client_id") == ""
    assert not any(settings["api_key_configured"].values())
    assert fetch("/api/settings", method="POST", body=b'{"provider":"gemini"}', extra={"Content-Type": "application/json"})[0] == 403
    for name, record in json.loads((HERE / "sources.json").read_text()).items():
        status, body, headers = fetch("/vendor/photo/sources/" + name)
        assert status == 200, (name, status)
        assert hashlib.sha256(body).hexdigest() == record["sha256"]
        assert "noindex" in headers["X-Robots-Tag"]
    status, body, _ = fetch("/identify", method="POST", body=b"x" * (6 * 1024 * 1024 + 16385))
    assert status == 400, (status, body[:200])
    print("PASS: auth gate, real app, current bundle, sources, settings, no diagnostics, upload bound")

if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8795")
