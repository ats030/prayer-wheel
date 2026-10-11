"""Offline browser + real local HTTP test of Google-login integration.

Virtual HTTPS origin permits Secure cookies. Google responses are fixtures, not
real account authentication. The production provider transport is never called.
"""
from http.client import HTTPConnection
import html
import json
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright, expect

from google_login import GoogleLogin, ISSUER
from public_security import PublicBoundary
from public_server import make_server
from test_google_login import CLIENT, ORIGIN, jwt


def main():
    fixture = {"nonce": "", "deny": False, "broken": False, "offline": False, "start_busy": False}
    def exchange(fields):
        return jwt({"iss": ISSUER, "aud": CLIENT, "sub": "1234567890",
                    "nonce": "wrong" if fixture["broken"] else fixture["nonce"],
                    "iat": int(time.time()), "exp": int(time.time()) + 3600})
    login = GoogleLogin(PublicBoundary(ORIGIN, b"x" * 32, ISSUER), CLIENT, "test-secret", exchange=exchange)
    server = make_server(login, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    trace = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context()
            def proxy(route):
                request = route.request
                url = urlsplit(request.url)
                trace.append({"path": url.path, "method": request.method, "cookie": "cookie" in request.all_headers()})
                if fixture["offline"] and url.path == "/api/session":
                    return route.fulfill(status=503, content_type="application/json", body='{"error":"offline"}')
                if fixture["start_busy"] and url.path == "/auth/google/start":
                    return route.fulfill(status=503, content_type="application/json", body='{"error":"login_capacity"}')
                headers = {key: value for key, value in request.all_headers().items()
                           if key.lower() not in ("host", "content-length", "connection", "accept-encoding")}
                headers["Host"] = "timeline.example"
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    path = url.path + ("?" + url.query if url.query else "")
                    connection.request(request.method, path, body=request.post_data, headers=headers)
                    response = connection.getresponse()
                    trace[-1]["status"] = response.status
                    outgoing, cookies = {}, []
                    for name, value in response.getheaders():
                        if name.lower() == "set-cookie":
                            cookies.append(value)
                        elif name.lower() not in ("connection", "content-length"):
                            outgoing[name] = value
                    if cookies:
                        outgoing["Set-Cookie"] = "\n".join(cookies)
                    body = response.read()
                    if response.status == 303:
                        # Playwright does not route redirected requests. A meta
                        # navigation starts a fresh routed request at the virtual
                        # HTTPS origin; real HTTP 303 is covered by unit tests.
                        target = outgoing.pop("Location")
                        outgoing["Content-Type"] = "text/html; charset=utf-8"
                        body = ('<meta http-equiv="refresh" content="0;url=' + html.escape(target, quote=True) + '">').encode()
                        route.fulfill(status=200, headers=outgoing, body=body)
                    else:
                        route.fulfill(status=response.status, headers=outgoing, body=body)
                finally:
                    connection.close()
            def google(route):
                trace.append({"path": "google-authorize"})
                params = parse_qs(urlsplit(route.request.url).query)
                fixture["nonce"] = params["nonce"][0]
                fields = {"state": params["state"][0], "error": "access_denied"} if fixture["deny"] else {
                    "state": params["state"][0], "code": "fixture-code"}
                target = ORIGIN + "/auth/google/callback?" + urlencode(fields)
                route.fulfill(status=200, content_type="text/html", body='<meta http-equiv="refresh" content="0;url=' + html.escape(target, quote=True) + '">')
            context.route(ORIGIN + "/**", proxy)
            context.route("https://accounts.google.com/**", google)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(ORIGIN + "/login")
            page.locator("#login-start").wait_for(state="visible")
            assert "まだログイン" in page.locator("#login-status").inner_text()
            page.locator("#login-start").click()
            try:
                page.locator("#login-logout").wait_for(state="visible", timeout=10000)
            except Exception:
                print(json.dumps({"trace": trace, "cookies": [cookie["name"] for cookie in context.cookies()],
                                  "path": urlsplit(page.url).path}), flush=True)
                raise
            assert page.url == ORIGIN + "/login"
            cookies = context.cookies()
            session = next(cookie for cookie in cookies if cookie["name"] == "__Host-timeline_session")
            assert session["secure"] and session["httpOnly"] and session["sameSite"] == "Lax"
            assert not any(cookie["name"] == "__Host-timeline_login" for cookie in cookies)
            page.reload()
            page.locator("#login-logout").wait_for(state="visible")
            page.locator("#login-logout").click()
            page.locator("#login-start").wait_for(state="visible")
            assert "ログアウトしました" in page.locator("#login-status").inner_text()
            assert not any(cookie["name"] == "__Host-timeline_session" for cookie in context.cookies())

            fixture["deny"] = True
            page.locator("#login-start").click()
            page.locator("#login-error").wait_for(state="visible")
            assert "取り消しました" in page.locator("#login-error").inner_text()
            assert page.url == ORIGIN + "/login"
            fixture["deny"], fixture["broken"] = False, True
            page.locator("#login-start").wait_for(state="visible")
            page.locator("#login-start").click()
            expect(page.locator("#login-error")).to_contain_text("確認できませんでした")
            assert page.locator("#login-logout").is_hidden()
            fixture["broken"], fixture["offline"] = False, True
            page.goto(ORIGIN + "/login")
            page.locator("#login-retry").wait_for(state="visible")
            assert page.locator("#login-start").is_hidden()
            fixture["offline"] = False
            page.locator("#login-retry").click()
            page.locator("#login-start").wait_for(state="visible")
            fixture["start_busy"] = True
            page.locator("#login-start").click()
            expect(page.locator("#login-error")).to_contain_text("混み合って")
            assert page.locator("#login-start").is_enabled()
            fixture["start_busy"] = False

            for width in (320, 375, 414, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                for scale in (100, 200):
                    page.evaluate("value => document.documentElement.style.fontSize = value + '%'", scale)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, scale)
                    assert page.evaluate("""() => [...document.querySelectorAll('button:not([hidden])')].every(button => {
                      const box = button.getBoundingClientRect(); const range = document.createRange(); range.selectNodeContents(button);
                      return box.height >= 44 && [...range.getClientRects()].every(rect => rect.left >= box.left - 1 && rect.right <= box.right + 1);
                    })"""), (width, scale)
                if width in (320, 1280):
                    page.evaluate("document.documentElement.style.fontSize='100%'")
                    page.screenshot(path=f"/tmp/timeline-login-{width}.png", full_page=True)
            page.set_viewport_size({"width": 375, "height": 900})
            page.evaluate("document.documentElement.style.fontSize='100%'")
            page.goto(ORIGIN + "/login?error=%3Cscript%3Ealert(1)%3C/script%3E")
            page.locator("#login-start").wait_for(state="visible")
            assert page.locator("#login-error").is_hidden()
            page.locator("#login-start").focus()
            page.keyboard.press("Enter")
            page.locator("#login-logout").wait_for(state="visible")
            # Browser storage must contain no provider tokens or credentials.
            assert page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert not errors, errors
            print(json.dumps({"checks": "offline provider; real HTTP; Secure cookies; login/reload/logout; denial/invalid claims; retry/busy; keyboard; 5 widths/200%; no browser token storage", "errors": errors}))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
