#!/usr/bin/env python3
"""Exercise summary-only UI against fixture API responses on a preview server."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8534/"
keys = {
    "shiseki": ["about", "history", "remains", "access", "highlights"],
    "omatsuri": ["about", "history", "highlights", "flow", "access", "tourism"],
    "onsen": ["about", "history", "food", "efficacy", "access", "tourism"],
    "tokusan": ["about", "history", "production", "visit"],
}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    errors = []
    mode = {"fail": False}
    page.on("pageerror", lambda e: errors.append(str(e)))

    def config(route):
        data = route.fetch().json()
        data["summariesOnly"] = True
        route.fulfill(json=data)

    def summary(route):
        if mode["fail"]:
            route.fulfill(status=503, json={"error": "test unavailable"})
            return
        kind = route.request.url.split("/api/")[1].split("/")[0]
        sections = {key: {"status": "summarized", "summary": "検証用要約：" + key,
                          "source_url": "https://www.maff.go.jp/j/keikaku/syokubunka/k_ryouri/" if kind == "tokusan" else "https://ja.wikipedia.org/wiki/例"} for key in keys[kind]}
        # A checked absent section must stay hidden, with no raw fallback.
        sections["history"] = {"status": "no_source"}
        route.fulfill(json={"sections": sections})

    page.route("**/api/config", config)
    page.route("**/api/*/summary/*", summary)
    page.goto(url, wait_until="domcontentloaded")
    for kind in keys:
        page.locator("#tab-" + kind).click()
        page.wait_for_function("k=>window.midokoro?.kind===k", arg=kind)
        host = page.locator("#view-" + kind)
        card = host.locator("." + ("festival" if kind == "omatsuri" else kind) + "-card").first
        card.wait_for()
        card.click()
        host.locator("#detail-title").wait_for()
        page.wait_for_function("k=>document.querySelector('#view-'+k).shadowRoot.querySelector('#detail-content').textContent.includes('検証用要約：about')", arg=kind)
        if kind == "tokusan":
            assert host.locator("#detail-history").count() == 0
        else:
            assert not host.locator("#detail-history-section").is_visible()
        if kind == "shiseki":
            assert "検証用要約：highlights" in host.locator("#detail-highlights-body").inner_text()
        assert host.locator("details.section-source, .section-source-text").count() == 0, kind
        assert "原文を読む" not in host.locator("#detail-content").inner_text(), kind
        assert host.locator(".detail-facts").inner_text().strip(), kind
        assert host.locator('a[href*="public_data_license"]' if kind == "tokusan" else 'a[href*="creativecommons.org/licenses/by-sa/"]').count() > 0, kind
        host.locator(".detail-close").click()
    # Local cultural records have an id but no Wikidata QID or article.
    page.locator("#tab-shiseki").click()
    page.wait_for_function("window.midokoro.kind==='shiseki'")
    roster = json.loads((Path(__file__).resolve().parents[1] / "frontend/assets/shiseki/shiseki.json").read_text())
    local = next(item for item in roster if item.get("id") and not item.get("qid"))
    host = page.locator("#view-shiseki")
    host.locator("#keyword").fill(local["label_ja"])
    host.locator('.shiseki-card[data-key="' + local["id"] + '"]').click()
    page.wait_for_function("document.querySelector('#view-shiseki').shadowRoot.querySelector('.detail-description').textContent.includes('検証用要約：about')")
    host.locator(".detail-close").click()
    host.locator("#clear-filters").click()
    # A failed summary endpoint must display an error, never source prose.
    mode["fail"] = True
    host.locator(".shiseki-card").nth(1).click()
    page.wait_for_function("document.querySelector('#view-shiseki').shadowRoot.querySelector('.detail-description').textContent.includes('要約を読み込めませんでした')")
    assert "原文を読む" not in host.locator("#detail-content").inner_text()
    assert "読み込んでいます" not in host.locator("#detail-history-status").inner_text()
    assert not errors, errors
    print(json.dumps({"summary_only_categories": list(keys), "browser_errors": errors}, ensure_ascii=False))
    browser.close()
