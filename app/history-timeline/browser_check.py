"""Browser UI checks with explicit synthetic API responses; model tested by smoke.py."""
import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

URL = os.environ.get("TIMELINE_TEST_URL", "http://100.94.207.13:8532")
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(URL, wait_until="domcontentloaded")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow at {width}"
        for selector in ["#submit", ".quiet-link", "[data-query]"]:
            for element in page.locator(selector).all():
                assert element.evaluate("e => e.getBoundingClientRect().height >= 44"), f"small touch target: {selector}"
                assert element.evaluate("e => getComputedStyle(e).whiteSpace === 'nowrap'"), f"wrapped button: {selector}"
        page.screenshot(path=f"/tmp/history-timeline-{width}.png", full_page=True)
    ratios = page.evaluate("""() => {
      const canvas = document.createElement('canvas'), ctx = canvas.getContext('2d');
      const css = getComputedStyle(document.documentElement);
      const lum = name => { ctx.fillStyle = css.getPropertyValue('--color-' + name); ctx.fillRect(0,0,1,1); const rgb = Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3).map(v => {v /= 255; return v <= 0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4;}); return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722; };
      return [['ink','paper'],['muted','paper'],['muted','surface'],['accent','paper'],['accent-ink','accent'],['error','paper'],['focus','paper'],['focus','accent']].map(([a,b]) => { const x=lum(a), y=lum(b); return [a,b,(Math.max(x,y)+0.05)/(Math.min(x,y)+0.05)]; });
    }""")
    print('CONTRAST:', [(a, b, round(r, 2)) for a,b,r in ratios], flush=True)
    assert all(ratio >= (3 if name == 'focus' else 4.5) for name, _, ratio in ratios), ratios
    page.locator("#submit").click()
    assert page.locator("#form-error").is_visible()
    assert page.locator("#query").get_attribute("aria-invalid") == "true"
    pending = []
    page.route("**/api/timeline", lambda route: pending.append(route))
    page.locator("#query").fill("テストテーマ 1900年以降")
    page.locator("#query").press("Enter")
    page.wait_for_function("document.getElementById('submit').disabled")
    assert page.locator("#progress").is_visible()
    assert page.locator("#query").is_disabled()
    assert page.locator("#search-form").get_attribute("aria-busy") == "true"
    result = {"kind": "result", "theme": "テスト用の年表", "period": "1900年〜", "elapsed_seconds": 1.2, "notice": "この応答はブラウザ検証専用です。", "events": [{"year": 1971, "date": "1971年", "title": "テスト用の出来事", "description": '<script>window.injected=true</script> テスト本文。', "quote": "In 1971, a test event occurred.", "source": {"url": "https://example.org/history", "title": "Test history source"}}]}
    while not pending:
        page.wait_for_timeout(50)
    pending.pop(0).fulfill(status=200, content_type="application/x-ndjson", body=json.dumps({"kind": "progress", "stage": "verify", "message": "テスト用の照合中"}) + "\n" + json.dumps(result) + "\n")
    page.locator(".event").wait_for()
    page.wait_for_function("!document.getElementById('submit').disabled")
    assert not page.evaluate("Boolean(window.injected)")
    assert page.locator(".event p").first.inner_text().startswith("<script>")
    page.locator("summary").focus()
    page.keyboard.press("Enter")
    assert page.locator("blockquote").is_visible()
    assert page.locator(".source-link").get_attribute("rel") == "noopener noreferrer"
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"result overflow at {width}"
    page.screenshot(path="/tmp/history-timeline-result.png", full_page=True)
    page.locator("#refine").click()
    assert page.locator("#query").evaluate("e => e === document.activeElement")
    page.locator("#query").fill("テスト 空結果")
    page.locator("#submit").click()
    while not pending:
        page.wait_for_timeout(50)
    pending.pop(0).fulfill(status=200, content_type="application/x-ndjson", body=json.dumps(result | {"events": []}) + "\n")
    page.locator("#result-empty").wait_for()
    page.wait_for_function("!document.getElementById('submit').disabled")
    assert page.locator(".event").count() == 0
    page.locator("#submit").click()
    while not pending:
        page.wait_for_timeout(50)
    pending.pop(0).fulfill(status=503, content_type="application/json", body=json.dumps({"error": "テスト用の接続エラー"}))
    page.locator("#form-error").wait_for()
    assert page.locator("#form-error").inner_text() == "テスト用の接続エラー"
    assert page.locator("#query").is_enabled()
    assert errors == [], errors
    print("PASS: 320/375/414/768/1280 widths, keyboard, loading, evidence, XSS, refine, empty, error")
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        page.unroute("**/api/timeline")
        page.goto(URL, wait_until="domcontentloaded")
        query = " ".join(sys.argv[2:]) or "インターネット 1980年以降"
        page.locator("#query").fill(query)
        page.locator("#submit").click()
        page.wait_for_function("!document.getElementById('submit').disabled", timeout=200000)
        assert not page.locator("#form-error").is_visible(), page.locator("#form-error").inner_text()
        assert page.locator(".event").count() > 0, page.locator("#result-notice").inner_text()
        print("LIVE:", query, page.locator("#result-meta").inner_text(), flush=True)
        for event in page.locator(".event").all():
            print(event.locator(".event-date").inner_text(), event.locator("h3").inner_text(), event.locator("p").first.inner_text(), flush=True)
        page.set_viewport_size({"width": 1280, "height": 900})
        page.screenshot(path="/tmp/history-timeline-live.png", full_page=True)
        page.set_viewport_size({"width": 375, "height": 900})
        page.screenshot(path="/tmp/history-timeline-live-mobile.png", full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == [], errors
    browser.close()
