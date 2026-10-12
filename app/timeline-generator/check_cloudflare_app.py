"""Check the public adapter and shared files, without accessing credentials or private jobs."""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18767").rstrip("/")
ACCESS_PROTECTED = "--access-protected" in sys.argv[2:]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(path, method="GET", *, follow_redirects=True):
    req = urllib.request.Request(BASE + path, method=method,
                                 headers={"User-Agent": "TimelineGenerator-DeploymentCheck/1.0"})
    try:
        opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=20) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


for route, name in [("/", "index.html"), ("/library", "library.html"), ("/quality", "quality.html"),
                    ("/changelog", "changelog.html"), ("/timelines/pub-showa", "detail.html"),
                    ("/showa/", "detail.html"), ("/app.js", "app.js"), ("/local-library.js", "local-library.js"),
                    ("/tokens.css", "tokens.css"), ("/styles.css", "styles.css"), ("/favicon.svg", "favicon.svg")]:
    status, body, headers = request(route)
    assert status == 200, (route, status)
    assert body == (ROOT / "cloudflare/app-assets" / name).read_bytes(), route
    assert headers.get("X-Content-Type-Options") == "nosniff", route
    assert "frame-ancestors 'none'" in headers.get("Content-Security-Policy", ""), route
status, body, headers = request("/api/jobs")
data = json.loads(body)
assert status == 200 and not data["generation_available"] and data["total"] == 1
assert headers.get("Cache-Control") == "no-store"
assert data["jobs"][0]["id"] == "pub-showa" and "result" not in data["jobs"][0]
status, body, _ = request("/api/jobs/pub-showa")
job = json.loads(body)
assert status == 200 and job["read_only"] and len(job["result"]["events"]) == 50
assert job["result"]["source_mode"] == "unknown" and job["quality"] is None
assert request("/api/jobs", "POST")[0] == 503
assert request("/api/jobs/pub-showa/regenerate", "POST")[0] == 503
for path in ["/api/private/jobs", "/manage"]:
    status, _, headers = request(path, follow_redirects=False)
    if ACCESS_PROTECTED:
        target = urlsplit(headers.get("Location", ""))
        assert status == 302 and target.scheme == "https" and target.hostname == "divine-boat-f31d.cloudflareaccess.com", path
    else:
        assert status == 503, path
assert request("/api/jobs?offset=-1")[0] == 400
assert json.loads(request("/api/jobs?offset=50")[1])["jobs"] == []
for path in ["/api/jobs/1", "/api/receipts/1", "/api/byok/receipts", "/timelines/1", "/data/timelines.sqlite3",
             "/.env", "/server.py", "/_headers", "/not-a-timeline"]:
    assert request(path)[0] == 404, path
print("PASS: 11 shared routes byte-match, security headers, published-only API, disabled writes, pagination errors, private files/routes absent")
