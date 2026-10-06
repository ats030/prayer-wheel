#!/usr/bin/env python3
"""Check category switching, viewport, filters and revisit with installed Playwright."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
url=sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:8533/"
output=Path(__file__).resolve().parents[1]/"artifacts";output.mkdir(exist_ok=True)
kinds=["shiseki","omatsuri","onsen","tokusan"]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={"width":1440,"height":960})
    page=context.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
    page.goto(url,wait_until="domcontentloaded")
    page.wait_for_function("window.midokoro?.kind==='shiseki'")
    page.wait_for_function("document.querySelector('#view-shiseki').shadowRoot.querySelector('#result-count').textContent!=='0'")
    page.evaluate("()=>{midokoro.map.setView([32.8,130.7],9,{animate:false})}")
    counts={}
    for kind in kinds:
        page.locator("#tab-"+kind).click()
        page.wait_for_function("k=>window.midokoro?.kind===k",arg=kind)
        host=page.locator("#view-"+kind)
        page.wait_for_function("k=>Number(document.querySelector('#view-'+k).shadowRoot.querySelector('#result-count').textContent)>0",arg=kind)
        counts[kind]=int(host.locator("#result-count").inner_text())
        state=page.evaluate("({lat:midokoro.map.getCenter().lat,lng:midokoro.map.getCenter().lng,zoom:midokoro.map.getZoom()})")
        assert abs(state["lat"]-32.8)<1e-8 and abs(state["lng"]-130.7)<1e-8 and state["zoom"]==9,(kind,state)
        host.locator("#keyword").fill("zzzz-no-matching-map-point")
        assert host.locator("#result-count").inner_text()=="0",kind
        host.locator("#clear-filters").click()
        assert int(host.locator("#result-count").inner_text())==counts[kind]
    # Each domain retains its detail panel, attribution and close behavior.
    for kind in kinds:
        page.locator("#tab-"+kind).click();page.wait_for_function("k=>midokoro.kind===k",arg=kind)
        host=page.locator("#view-"+kind)
        card=host.locator("."+("festival" if kind=="omatsuri" else kind)+"-card").first
        card.click();host.locator("#detail-title").wait_for()
        assert host.locator("#detail-panel").is_visible()
        assert host.locator("#detail-title").inner_text().strip()
        host.locator(".detail-close").click()
        assert not host.locator("#detail-panel").is_visible()
    # Category filters and state remain in their own view.
    page.locator("#view-tokusan #keyword").fill("熊本")
    saved=page.locator("#view-tokusan #result-count").inner_text()
    page.locator("#tab-shiseki").click();page.locator("#tab-tokusan").click()
    page.wait_for_function("window.midokoro.kind==='tokusan'")
    assert page.locator("#view-tokusan #keyword").input_value()=="熊本"
    assert page.locator("#view-tokusan #result-count").inner_text()==saved
    page.locator("#view-tokusan #clear-filters").click()
    page.goto(url,wait_until="domcontentloaded")
    page.wait_for_function("window.midokoro?.kind==='tokusan'")
    page.wait_for_function("Number(document.querySelector('#view-tokusan').shadowRoot.querySelector('#result-count').textContent)>0")
    assert page.locator('.leaflet-container').count()==1
    # Arrow keys select categories and move focus.
    page.locator("#tab-tokusan").focus();page.keyboard.press("Home")
    page.wait_for_function("window.midokoro.kind==='shiseki'")
    assert page.locator("#tab-shiseki").evaluate("el=>el===document.activeElement")
    # Test rapid changes including first mount and restored views.
    for kind in ["omatsuri","onsen","shiseki","tokusan"]: page.locator("#tab-"+kind).click()
    page.wait_for_function("window.midokoro.kind==='tokusan' && document.querySelector('#status').hidden")
    assert page.locator('[role=tabpanel]:visible').count()==1
    for width in [320,375,414,768,1440]:
        page.set_viewport_size({"width":width,"height":960})
        for kind in kinds:
            page.locator("#tab-"+kind).click();page.wait_for_function("k=>window.midokoro.kind===k",arg=kind)
            page.wait_for_timeout(150)
            overflow=page.evaluate("document.documentElement.scrollWidth>innerWidth || document.body.scrollWidth>innerWidth")
            assert not overflow,(width,kind)
            rect=page.locator('#view-'+kind+' #map').bounding_box()
            assert rect and rect['width']>200 and rect['height']>200,(width,kind,rect)
        page.screenshot(path=str(output/f"map-{width}.png"),full_page=True)
    assert not errors,errors
    print(json.dumps({"url":url,"counts":counts,"browser_errors":errors,"checks":"viewport preserved, filters, detail panels, per-kind state, revisit, keyboard, rapid switch, 5 widths"},ensure_ascii=False))
    browser.close()
