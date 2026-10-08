"""Check the protected real app without user data or external AI requests."""
import base64
import hashlib
from http.cookies import SimpleCookie
import json
from pathlib import Path
import sys
import uuid
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
STATE = Path('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None

def check(origin, oauth_enabled=False):
    secrets = json.loads(STATE.read_text())
    password = secrets["IKIMONO_PREVIEW_PASSWORD"]
    client_id = secrets.get("IKIMONO_GOOGLE_CLIENT_ID", "")
    if oauth_enabled:
        assert client_id and secrets.get("IKIMONO_GOOGLE_CLIENT_SECRET"), "OAuth bindings missing from private state"
    credential = "Basic " + base64.b64encode(("preview:" + password).encode()).decode()
    def fetch(path, authenticated=True, method="GET", body=None, extra=None):
        headers = {"Authorization": credential} if authenticated else {}
        headers["User-Agent"] = "ikimono-note-deployment-check/1.0"
        headers.update(extra or {})
        try:
            # Inspect redirects locally; never forward preview credentials to Google.
            response = build_opener(NoRedirect).open(
                Request(origin + path, data=body, method=method, headers=headers), timeout=30)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    for path in ("/", "/health", "/assets/index.js", "/vendor/photo/libheif.mjs",
                 "/vendor/photo/sources/libheif.tar.gz", "/api/settings", "/auth/google",
                 "/auth/callback", "/probe/profile/native-health"):
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
    for name in ("X-Preview-Isolate", "X-Preview-Isolate-Invocation"):
        assert name not in headers, "Ordinary response exposed operator observation"
    probe_headers = {"X-Ikimono-CPU-Probe": "0123abcd"}
    previous = {}
    for path in ("/health", "/api/me", "/assets/index.js", "/health"):
        status, _, observed = fetch(path, extra=probe_headers)
        assert status == 200, path
        identifier = observed["X-Preview-Isolate"]
        assert str(uuid.UUID(identifier)) == identifier
        invocation = int(observed["X-Preview-Isolate-Invocation"])
        assert invocation > previous.get(identifier, 0)
        previous[identifier] = invocation
    for authenticated, marker in ((False, "0123abcd"), (True, "invalid")):
        _, _, observed = fetch("/health", authenticated, extra={"X-Ikimono-CPU-Probe": marker})
        assert "X-Preview-Isolate" not in observed and "X-Preview-Isolate-Invocation" not in observed
    me = json.loads(fetch("/api/me")[1])
    assert me["available"] is oauth_enabled and me["signed_in"] is False, me.keys()
    for path in ("/", "/login", "/changelog", "/assets/index.js", "/vendor/photo/libheif.mjs"):
        status, body, headers = fetch(path)
        assert status == 200, (path, status, body[:100])
        assert headers["Cache-Control"] == "no-store"
    assert "Cloudflare検証版" in fetch("/changelog")[1].decode()
    assert fetch("/probe/profile/native-health")[0] == 404
    for path in ("/.env", "/src/worker.py", "/secrets.json"):
        status, body, headers = fetch(path)
        if oauth_enabled:
            assert status == 303 and headers["Location"] == "/login" and not body, path
        else:
            assert status == 404, path
    for path in ("/settings", "/history"):
        status, _, headers = fetch(path)
        if oauth_enabled:
            assert status == 303 and headers["Location"] == "/login", (path, status)
        else:
            assert status == 200, (path, status)
    if oauth_enabled:
        assert fetch("/api/settings")[0] == 401
    else:
        settings = json.loads(fetch("/api/settings")[1])
        assert settings.get("browser_photos") is True, settings.keys()
        assert settings.get("google_client_id") == ""
        assert not any(settings["api_key_configured"].values())
    status, _, headers = fetch("/auth/google")
    flow_cookie = None
    if oauth_enabled:
        assert status == 303, status
        target = urlsplit(headers["Location"])
        assert (target.scheme, target.hostname, target.path) == (
            "https", "accounts.google.com", "/o/oauth2/v2/auth")
        params = parse_qs(target.query)
        assert params["client_id"] == [client_id]
        public_origin = json.loads((HERE / "wrangler.jsonc").read_text())["vars"]["IKIMONO_PUBLIC_ORIGIN"]
        assert params["redirect_uri"] == [public_origin + "/auth/callback"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert params.get("state") and params.get("nonce") and params.get("code_challenge")
        cookie = headers["Set-Cookie"].lower()
        assert all(flag in cookie for flag in ("httponly", "secure", "samesite=lax", "path=/auth"))
        cookies = SimpleCookie()
        cookies.load(headers["Set-Cookie"])
        flow_cookie = "ikimono_login=" + cookies["ikimono_login"].value
        second_status, _, second_headers = fetch("/auth/google")
        assert second_status == 303
        second_params = parse_qs(urlsplit(second_headers["Location"]).query)
        for name in ("state", "nonce", "code_challenge"):
            assert second_params.get(name) and second_params[name] != params[name], name
    else:
        assert status == 503, status
    status, _, headers = fetch("/auth/callback?code=invalid&state=invalid")
    assert status == 303 and headers["Location"] == "/login?failed=1"
    assert "ikimono_session=" not in headers.get("Set-Cookie", "")
    if flow_cookie:
        status, _, headers = fetch("/auth/callback?code=invalid&state=invalid",
                                   extra={"Cookie": flow_cookie})
        assert status == 303 and headers["Location"] == "/login?failed=1"
        assert "ikimono_session=" not in headers.get("Set-Cookie", "")
    assert fetch("/api/settings", method="POST", body=b'{"provider":"gemini"}', extra={"Content-Type": "application/json"})[0] == (401 if oauth_enabled else 403)
    for name, record in json.loads((HERE / "sources.json").read_text()).items():
        status, body, headers = fetch("/vendor/photo/sources/" + name)
        assert status == 200, (name, status)
        assert hashlib.sha256(body).hexdigest() == record["sha256"]
        assert "noindex" in headers["X-Robots-Tag"]
    reference_headers = fetch("/login")[2]
    security_headers = ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
                        "Referrer-Policy", "Permissions-Policy", "Cross-Origin-Opener-Policy")
    for path in namespace.get("NATIVE_ASSET_PATHS", ()):
        if path.startswith("/vendor/photo/sources/"):
            continue  # Source archive integrity is checked above.
        assert fetch(path, False)[0] == 401, path
        status, body, headers = fetch(path)
        assert status == 200 and body == (HERE / "assets" / path.lstrip("/")).read_bytes(), path
        assert all(headers.get(name) == reference_headers.get(name) for name in security_headers), path
        status, head_body, head_headers = fetch(path, method="HEAD")
        assert status == 200 and not head_body, path
        assert head_headers["Content-Length"] == str(len(body)), path
        if path.startswith("/downloads/"):
            assert headers["Content-Disposition"] == 'attachment; filename="' + path.rsplit("/", 1)[1] + '"', path
    path = "/assets/index.js"
    status, body, headers = fetch(path)
    assert headers["Content-Type"].split(";")[0] in {"text/javascript", "application/javascript"}
    if namespace.get("NATIVE_ASSET_PATHS"):
        assert fetch(path, extra={"If-None-Match": headers["ETag"]})[0] == 304
        status, _, headers = fetch(path, method="POST", body=b"ignored")
        assert status == 405 and headers["Allow"] == "GET, HEAD"
        assert headers["Cache-Control"] == "no-store" and "noindex" in headers["X-Robots-Tag"]
        if urlsplit(origin).hostname in {"localhost", "127.0.0.1"}:
            # Cloudflare rejects mismatched Host at its edge; exercise the
            # Worker's own guard without sending credentials to another host.
            assert fetch(path, extra={"Host": "attacker.invalid"})[0] == 400
        for unknown in ("/assets/not-allowed.js", "/vendor/photo/sources/not-allowed"):
            assert fetch(unknown)[0] == 404, unknown
        status, body, headers = fetch("/assets/%2e%2e/.env")
        # URL normalization can reach the same login guard as /.env.
        assert status == 404 or (oauth_enabled and status == 303
                                 and headers["Location"] == "/login" and not body)
    status, body, _ = fetch("/identify", method="POST", body=b"x" * (6 * 1024 * 1024 + 16385))
    assert status == 400, (status, body[:200])
    print("PASS: auth gate, real app, current bundle, sources, settings, OAuth start/state rejection, no diagnostics, upload bound")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin", nargs="?", default="http://127.0.0.1:8795")
    parser.add_argument("--oauth", action="store_true", help="Expect configured Google login (does not sign in)")
    args = parser.parse_args()
    check(args.origin, args.oauth)
