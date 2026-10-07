#!/usr/bin/env python3
"""Exercise actual story navigation, failure recovery, privacy and shared URLs."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright

origin = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8533").rstrip("/")
path = "/stories/arita-porcelain"
artifacts = Path(__file__).resolve().parents[1] / "artifacts"
artifacts.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors, events = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: events.append(request.url.rsplit("/", 1)[-1]) if "/api/story-events/" in request.url else None)
    # Avoid tile network availability deciding the outcome of interaction tests.
    page.route("https://tile.openstreetmap.org/**", lambda route: route.fulfill(status=200, content_type="image/png", body=bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082")))
    page.goto(origin + path + "?from=home")
    page.locator("#selected-place h3").wait_for()
    assert page.locator("#selected-place h3").inner_text() == "泉山磁石場"
    assert page.locator(".leaflet-marker-icon").count() == 5
    assert page.locator(".leaflet-control-attribution").is_visible()
    page.locator('.question-links [data-relation="kiln-wall"]').focus()
    page.keyboard.press("Enter")
    assert page.locator("#selected-place h3").inner_text() == "トンバイ塀のある裏通り"
    assert "未確認" in page.locator("#selected-relation").inner_text()
    # Reverse traversal must survive reload and sharing, not just the relation ID.
    page.locator('#related-places [data-relation="kiln-wall"]').click()
    assert page.locator("#selected-place h3").inner_text() == "天狗谷窯跡"
    assert parse_qs(urlsplit(page.url).query)["place"] == ["tengudani"]
    reversed_url = page.url
    page.reload()
    page.locator("#selected-place h3").wait_for()
    assert page.locator("#selected-place h3").inner_text() == "天狗谷窯跡"
    # Fixed path events are sent once per page, with no body/identifier.
    events.clear()
    page.goto(origin + path + "?from=shared#stone-museum")
    page.locator("#selected-place h3").wait_for()
    page.locator('.place-links [data-place="sueyama"]').click()
    page.locator('.place-links [data-place="izumiyama"]').click()
    page.locator('#related-places [data-relation="stone-museum"]').click()
    page.locator('#related-places [data-relation="stone-museum"]').click()
    page.wait_for_timeout(200)
    assert {"view", "entry-shared", "explore", "follow"}.issubset(events), events
    assert len(events) == len(set(events)), events
    # A rejected clipboard write exposes a selectable URL with exact state.
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true,value:{writeText:()=>Promise.reject(new Error('denied'))}})")
    page.locator("#copy-story").click()
    page.locator("#manual-share").wait_for(state="visible")
    shared = page.locator("#share-url").input_value()
    assert parse_qs(urlsplit(shared).query)["from"] == ["shared"]
    assert parse_qs(urlsplit(shared).query)["place"] == ["izumiyama"]
    assert urlsplit(shared).fragment == "stone-museum"
    page.goto(shared)
    page.locator("#selected-place h3").wait_for()
    assert page.locator("#selected-place h3").inner_text() == "泉山磁石場"
    assert "大皿" in page.locator("#selected-relation").inner_text()
    # Successful clipboard operation and rejected Web Share are separate signals.
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable:true,value:{writeText:async()=>{}}})")
    page.locator("#copy-story").click()
    page.wait_for_function("document.querySelector('#share-status').textContent.includes('コピーしました')")
    assert not page.locator("#manual-share").is_visible()
    for width in [320, 375, 768, 1440]:
        page.set_viewport_size({"width": width, "height": 1000})
        page.locator('.place-links [data-place="museum"]').click()
        page.wait_for_timeout(100)
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
        rect = page.locator("#story-map").bounding_box()
        assert rect and rect["width"] > 250 and rect["height"] >= 330, (width, rect)
        assert page.locator("#selected-place .source a").first.is_visible()
        page.screenshot(path=str(artifacts / f"story-{width}.png"), full_page=True)
    # Map marker selection also updates the accessible text panel.
    page.locator('.leaflet-marker-icon[title="陶山神社"]').click()
    assert page.locator("#selected-place h3").inner_text() == "陶山神社"
    assert not errors, errors
    page.locator('.reading-link a').click()
    assert urlsplit(page.url).fragment == "places"
    page.reload()
    page.locator("#selected-place h3").wait_for()
    assert urlsplit(page.url).fragment == "places"
    page.goto(origin + path + "#relations")
    page.locator("#selected-place h3").wait_for()
    assert urlsplit(page.url).fragment == "relations"

    privacy = browser.new_context()
    privacy.add_init_script("Object.defineProperty(navigator,'doNotTrack',{get:()=> '1'}); Object.defineProperty(navigator,'share',{value:async()=>{throw new Error('unavailable')}})")
    private = privacy.new_page()
    private_events = []
    private.on("request", lambda request: private_events.append(request.url) if "/api/story-events/" in request.url else None)
    private.route("**/vendor/leaflet.js", lambda route: route.abort())
    private.goto(origin + path)
    private.locator("#selected-place h3").wait_for()
    assert "地図を読み込めません" in private.locator("#map-status").inner_text()
    private.locator('.question-links [data-relation="stone-shrine"]').click()
    assert "伝承" in private.locator("#selected-relation").inner_text()
    private.locator("#share-story").click()
    private.locator("#manual-share").wait_for(state="visible")
    assert "共有画面を開けません" in private.locator("#share-status").inner_text()
    assert not private_events, private_events

    sharing_context = browser.new_context()
    sharing_context.add_init_script("Object.defineProperty(navigator,'share',{configurable:true,value:async()=>{}})")
    sharing_page = sharing_context.new_page()
    share_events = []
    sharing_page.on("request", lambda request: share_events.append(request.url.rsplit("/",1)[-1]) if "/api/story-events/" in request.url else None)
    sharing_page.route("**/vendor/leaflet.js", lambda route: route.abort())
    sharing_page.goto(origin + path)
    sharing_page.locator("#share-story").click()
    sharing_page.wait_for_function("document.querySelector('#share-status').textContent.includes('閉じました')")
    assert "share-returned" in share_events
    sharing_page.evaluate("Object.defineProperty(navigator,'share',{configurable:true,value:async()=>{throw new DOMException('cancel','AbortError')}})")
    sharing_page.locator("#share-story").click()
    sharing_page.wait_for_function("document.querySelector('#share-status').textContent.includes('キャンセル')")
    assert not sharing_page.locator("#manual-share").is_visible()
    assert not sharing_page.locator("#share-story").is_disabled()

    tiles_context = browser.new_context()
    tiles_page = tiles_context.new_page()
    tiles_page.route("https://tile.openstreetmap.org/**", lambda route: route.abort())
    tiles_page.goto(origin + path)
    tiles_page.wait_for_function("document.querySelector('#map-status').textContent.includes('背景地図')")
    tiles_page.locator('.place-links [data-place="tonbai"]').click()
    assert tiles_page.locator("#selected-place h3").inner_text() == "トンバイ塀のある裏通り"

    static = browser.new_context(java_script_enabled=False)
    static_page = static.new_page()
    static_page.goto(origin + path)
    assert static_page.locator(".place-articles article").count() == 5
    assert static_page.locator(".relation-articles li").count() == 5
    assert "伝承" in static_page.locator("#stone-shrine").inner_text()
    assert static_page.locator("#places .source a").count() >= 5
    assert not static_page.locator("#map-status").is_visible()
    assert static_page.get_by_text("地図を表示するにはJavaScriptが必要です。場所のリンクから、下の解説とつながりを読めます。").is_visible()
    page.goto(origin + "/")
    assert page.locator(".story-entry").get_attribute("href") == path + "?from=home"
    print(json.dumps({"checks": "5 places, keyboard, reverse traversal, URL reload/share, per-page event deduplication, clipboard fallback/success, Web Share failure, 4 widths, marker selection, Leaflet/tile failure, DNT, static HTML, home entry", "browser_errors": errors}, ensure_ascii=False))
    browser.close()
