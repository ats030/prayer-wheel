"""Exercise the real shared Cloudflare UI; never enqueue generation or modify server data."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18767").rstrip("/")

with TemporaryDirectory() as directory, sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE)
    page.locator("#job-list a").wait_for()
    assert page.locator("#generation-availability").inner_text().find("接続準備中") >= 0
    assert page.locator("#query").is_disabled() and page.locator("#submit").is_disabled()
    assert page.locator("#job-list .job-delete").count() == 0
    page.locator("#job-list a").click()
    page.locator("#timeline .event").first.wait_for()
    assert page.locator("#timeline .event").count() == 50
    assert page.locator("#retry").is_hidden() and page.locator("#regenerate").is_hidden()
    assert page.locator("#cancel").is_hidden() and page.locator("#milestones-section").is_hidden()
    assert page.locator("#publication-license a").get_attribute("href").startswith("https://creativecommons.org/")
    assert not page.locator('script[src*="ubuntu-server-app"]').count()
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({"width": width, "height": 900})
        for zoom in [1, 2]:
            page.evaluate("zoom => document.documentElement.style.fontSize = `${zoom * 100}%`", zoom)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, zoom)
        page.evaluate("document.documentElement.style.fontSize = '100%'")
    page.locator("#local-save").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('#local-save-status').textContent.includes('保存しました')")
    with page.expect_download() as download:
        page.locator("#local-download").click()
    path = Path(directory) / "showa.json"
    download.value.save_as(path)
    portable = json.loads(path.read_text())
    record = portable["timelines"][0]
    assert len(record["events"]) == 50 and record["source_mode"] == "unknown"
    assert "CC BY-SA 4.0" in record["notice"]
    assert "quote" not in record["events"][0] and "trace" not in record
    page.goto(BASE + "/library")
    page.wait_for_function("() => document.querySelector('#local-count').textContent.includes('1件')")
    page.locator("#local-list details").evaluate("element => element.open = true")
    assert page.locator("#local-list .event").count() == 50
    page.locator("#local-import").set_input_files(path)
    page.wait_for_function("() => document.querySelector('#local-status').textContent.includes('0件を追加')")
    page.reload()
    page.wait_for_function("() => document.querySelector('#local-count').textContent.includes('1件')")
    page.route("**/api/jobs*", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"接続テスト失敗"}'))
    page.goto(BASE)
    page.locator("#page-error").wait_for(state="visible")
    assert page.locator("#submit").is_disabled()
    assert "接続テスト失敗" in page.locator("#page-error").inner_text()
    assert not errors, errors
    browser.close()
print("PASS: published 50 events, generation disabled, no private operations, attribution, 5 widths/200%, keyboard save, real IndexedDB persistence, download/import roundtrip, failure state")
