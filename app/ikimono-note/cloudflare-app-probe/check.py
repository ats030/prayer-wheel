"""Exercise the real application on loopback Workers, without external APIs."""
import json
import base64
import hashlib
import hmac
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from build import bundle_digest

HERE = Path(__file__).resolve().parent
ORIGIN = "http://localhost:8793"
PAGES = {
    "index.html": "/", "login.html": "/login", "settings.html": "/settings",
    "history.html": "/history", "dashboard.html": "/dashboard",
    "privacy.html": "/privacy", "terms.html": "/terms",
    "changelog.html": "/changelog", "android-original.html": "/android-original",
}


def fetch(path, method="GET", data=None, headers=None):
    request = Request(ORIGIN + path, method=method, data=data, headers=headers or {})
    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


def check():
    manifest = json.loads((HERE / "manifest.json").read_text())
    assert fetch("/health")[2]["X-Probe-Synthetic-AI"] == "1", "Probe requires synthetic AI; never use real keys"
    for name in manifest["modules"]:
        assert (HERE / "src" / name).read_bytes() == (HERE.parent / name).read_bytes(), (
            "Stale module; run build.py", name)
    assert fetch("/health")[2]["X-Probe-Bundle-SHA256"] == bundle_digest(manifest), (
        "Running Worker is stale; rebuild and wait for reload")
    checked = 0
    for name in manifest["resources"]:
        if not name.startswith("static/") or name == "static/share.html":
            continue
        relative = name.removeprefix("static/")
        path = PAGES.get(relative, "/" + relative)
        status, body, headers = fetch(path)
        assert status == 200, (path, status, body[:200])
        assert headers["X-Content-Type-Options"] == "nosniff", path
        assert "unsafe-inline" not in headers["Content-Security-Policy"], path
        original = (HERE.parent / name).read_bytes()
        if relative in PAGES:
            assert b'data-app-mode="public"' in body, path
            assert b"/assets/analytics.js" in body, path
        else:
            assert body == original, path
        if relative.endswith(".apk"):
            assert headers["Accept-Ranges"] == "bytes", path
            etag = headers["ETag"]
            status, partial, range_headers = fetch(path, headers={"Range": "bytes=3-11"})
            assert status == 206 and partial == original[3:12], path
            assert range_headers["Content-Range"] == f"bytes 3-11/{len(original)}"
            assert fetch(path, headers={"Range": "bytes=-7"})[1] == original[-7:]
            assert fetch(path, headers={"Range": "bytes=0-2", "If-Range": etag})[0] == 206
            assert fetch(path, headers={"Range": "bytes=0-2", "If-Range": '"stale"'})[1] == original
            assert fetch(path, headers={"Range": f"bytes={len(original)}-"})[0] == 416
            assert fetch(path, headers={"Range": "invalid"})[0] == 400
            status, multiple, multi_headers = fetch(path, headers={"Range": "bytes=0-2,8-11"})
            assert status == 206 and "multipart/byteranges" in multi_headers["Content-Type"]
            boundary = multi_headers["Content-Type"].split("boundary=", 1)[1]
            expected = b"".join(
                (f"--{boundary}\r\nContent-Type: application/vnd.android.package-archive\r\n"
                 f"Content-Range: bytes {start}-{end-1}/{len(original)}\r\n\r\n").encode()
                + original[start:end] + b"\r\n" for start, end in [(0, 3), (8, 12)])
            assert multiple == expected + f"--{boundary}--".encode()
            if multi_headers["Content-Length"] is not None:
                assert len(multiple) == int(multi_headers["Content-Length"])
            status, head, _ = fetch(path, "HEAD", headers={"Range": "bytes=3-11"})
            # Existing FastAPI GET-only download routes reject HEAD.
            assert status == 405 and not head
        if relative.startswith(("assets/", "vendor/")):
            etag = headers["ETag"]
            for validator in (etag, "W/" + etag, '"stale", ' + etag, "*"):
                status, cached, _ = fetch(path, headers={"If-None-Match": validator})
                assert status == 304 and not cached, path
            assert fetch(path, headers={"If-None-Match": '"stale"'})[1] == original
            status, head, head_headers = fetch(path, "HEAD")
            assert status == 200 and not head, path
            assert int(head_headers["Content-Length"]) == len(original), path
        checked += 1
    for path in (
        "/.env", "/main.py", "/_resources.py", "/data/protected_species.json",
        "/settings.json", "/assets/../main.py", "/vendor/%2e%2e/main.py",
        "/assets/", "/vendor/", "/docs", "/openapi.json",
    ):
        assert fetch(path)[0] == 404, path
    status, body, headers = fetch("/assets/index.js", "POST", b"")
    assert status == 405 and headers["Allow"] == "GET, HEAD"
    assert json.loads(fetch("/health")[1]) == {"ok": True}
    settings = json.loads(fetch("/api/settings")[1])
    assert settings["public_mode"] and not any(settings["api_key_configured"].values())
    assert fetch("/api/settings", "POST", b'{"provider":"gemini"}',
                 {"Content-Type": "application/json"})[0] == 403
    assert fetch("/health", headers={"Host": "attacker.invalid"})[0] == 400
    assert fetch("/s/nonexistent-token")[0] == 404
    assert fetch("/s/nonexistent-token/photo")[0] == 404
    result = {"category": "動物", "candidates": [{
        "common_name_ja": "イタセンパラ", "scientific_name": "Acheilognathus longipinnis",
        "confidence": 30, "traits": ["合成検証"], "uncertainty": "合成検証",
    }]}
    status, body, _ = fetch("/api/local/result", "POST",
                            json.dumps({"text": json.dumps(result)}).encode(),
                            {"Content-Type": "application/json"})
    assert status == 200, body
    species = json.loads(body)["candidates"][0]["protected_species"]
    assert species["common_name_ja"] == "イタセンパラ" and species["as_of"] == "令和7年2月"
    # Synthetic local session exercises the signed-cookie/D1/share-page path.
    # This is not Google OAuth verification and never uses a real identity.
    def cookie(subject):
        payload = json.dumps({"sub": subject, "email": "synthetic@example.invalid",
                              "exp": int(time.time()) + 300}, separators=(",", ":")).encode()
        body = base64.urlsafe_b64encode(payload).rstrip(b"=")
        secret = "synthetic-local-app-probe-never-deploy"
        signature = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        return "ikimono_session=" + (body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()

    photo = (HERE.parent / "static/favicon.png").read_bytes()
    candidates = json.dumps([{"common_name_ja": "合成検証", "confidence": 30,
                              "traits": ["合成特徴"], "userNote": "PRIVATE-DO-NOT-PUBLISH"}]).encode()
    boundary = b"paskw-local-probe"
    multipart = (b"--" + boundary + b'\r\nContent-Disposition: form-data; name="candidates"\r\n\r\n'
                 + candidates + b"\r\n--" + boundary
                 + b'\r\nContent-Disposition: form-data; name="photo"; filename="probe.png"\r\n'
                 + b"Content-Type: image/png\r\n\r\n" + photo + b"\r\n--" + boundary + b"--\r\n")
    headers = {"Cookie": cookie("synthetic-app-probe"),
               "Content-Type": "multipart/form-data; boundary=" + boundary.decode()}
    status, body, _ = fetch("/api/share", "POST", multipart, headers)
    assert status == 200, body
    token = json.loads(body)["token"]
    try:
        status, page, _ = fetch("/s/" + token)
        assert status == 200 and "合成検証" in page.decode()
        assert b"PRIVATE-DO-NOT-PUBLISH" not in page
        assert fetch("/s/" + token + "/photo")[1] == photo
        assert fetch("/api/share/" + token + "/delete", "POST", b"",
                     {"Cookie": cookie("synthetic-other-owner")})[0] == 404
    finally:
        assert fetch("/api/share/" + token + "/delete", "POST", b"", headers)[0] == 200
    assert fetch("/s/" + token)[0] == 404
    assert fetch("/s/" + token + "/photo")[0] == 404
    print(f"PASS: {checked} public resources; headers, HEAD, API, D1 reads, access boundaries")


if __name__ == "__main__":
    check()
