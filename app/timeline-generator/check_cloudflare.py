"""Check deployed static assets byte-for-byte and ensure APIs are absent."""
import argparse
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def open_url(url):
    return urlopen(Request(url, headers={"User-Agent": "timeline-generator-deployment-check/1.0"}), timeout=30)


def check(origin):
    origin = origin.rstrip("/")
    assets = ROOT / "cloudflare" / "assets"
    count = 0
    for path in sorted(assets.rglob("*")):
        if not path.is_file() or path.name.startswith("_"):
            continue
        relative = path.relative_to(assets).as_posix()
        route = "/" + relative.removesuffix("index.html") if path.name == "index.html" else "/" + relative
        with open_url(origin + route) as response:
            assert response.status == 200, route
            assert response.read() == path.read_bytes(), f"Content mismatch: {route}"
            assert response.headers.get("X-Content-Type-Options") == "nosniff", route
            assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin", route
            assert "default-src 'none'" in response.headers.get("Content-Security-Policy", ""), route
            assert "max-age=300" in response.headers.get("Cache-Control", ""), route
        if route != "/" and path.name == "index.html":
            with open_url(origin + route.rstrip("/")) as response:
                assert response.url == origin + route, response.url
        count += 1
    for route in ("/not-a-timeline", "/api/jobs", "/api/byok/receipts", "/_headers", "/data/private.sqlite3"):
        try:
            with open_url(origin + route):
                raise AssertionError(f"Unexpected public route: {route}")
        except HTTPError as exc:
            assert exc.code == 404, (route, exc.code)
    print(f"Verified {count} public assets, security headers, trailing slash and 5 absent routes: {origin}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("origin")
    check(parser.parse_args().origin)
