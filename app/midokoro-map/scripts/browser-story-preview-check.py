#!/usr/bin/env python3
"""Verify a generated draft bundle without changing published stories."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def check(bundle, browser):
    bundle = Path(bundle).resolve()
    packet = json.loads((bundle / "packet.json").read_text())
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietFiles, directory=str(bundle / "preview")))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    events, errors = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: events.append(request.url) if "/api/story-events/" in request.url else None)
    page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
    page.route("http://ubuntu-server-app:8526/**", lambda route: route.abort())
    try:
        page.goto(origin)
        page.locator("#selected-place h3").wait_for()
        assert page.locator("#selected-place h3").inner_text() == packet["places"][0]["name"]
        assert page.locator(".leaflet-marker-icon").count() == 5
        assert page.locator(".relation-articles li").count() == 5
        relation_id = page.locator(".question-links a").first.get_attribute("data-relation")
        page.locator(".question-links a").first.focus()
        page.keyboard.press("Enter")
        assert page.locator("#selected-relation").is_visible()
        destination = page.locator(".place-links [aria-current]").get_attribute("data-place")
        page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:()=>Promise.reject(new Error('denied'))}})")
        page.locator("#copy-story").click()
        page.locator("#manual-share").wait_for(state="visible")
        shared = page.locator("#share-url").input_value()
        assert urlsplit(shared).path == "/stories/" + packet["slug"]
        assert urlsplit(shared).fragment == relation_id
        page.goto(shared)  # Static server redirects to directory, retaining query/hash.
        page.locator("#selected-place h3").wait_for()
        assert page.locator(".place-links [aria-current]").get_attribute("data-place") == destination
        for width in [320, 375, 768, 1440]:
            page.set_viewport_size({"width": width, "height": 1000})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
        page.screenshot(path=str(bundle / "preview-desktop.png"), full_page=True)
        page.set_viewport_size({"width":375,"height":900})
        page.screenshot(path=str(bundle / "preview-mobile.png"), full_page=True)
        assert not events, events
        assert not errors, errors
        static = browser.new_context(java_script_enabled=False)
        static_page = static.new_page()
        static_page.goto(origin)
        assert static_page.locator(".place-articles article").count() == 5
        assert static_page.locator(".relation-articles li").count() == 5
        assert static_page.locator("#static-map-note").is_visible()
        static.close()
        return {"bundle":str(bundle),"slug":packet["slug"],"errors":errors,"story_events":events,
                "checks":"five places/relations, keyboard, shared URL restoration, four widths, static HTML, no acquisition events"}
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: browser-story-preview-check.py <generated-bundle> [bundle...]")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for bundle in sys.argv[1:]:
                print(json.dumps(check(bundle, browser), ensure_ascii=False))
        finally:
            browser.close()
