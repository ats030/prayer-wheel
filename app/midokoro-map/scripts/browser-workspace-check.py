#!/usr/bin/env python3
"""Check workspace navigation, usable widths and focus across all categories."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8533/'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.midokoro?.kind')
    for width in [320, 375, 768, 900, 1440]:
        page.set_viewport_size({'width': width, 'height': 900})
        for kind in ['shiseki', 'omatsuri', 'onsen', 'tokusan', 'geo']:
            page.locator('#tab-' + kind).click()
            page.wait_for_function('k=>midokoro.kind===k && document.querySelector("#status").hidden', arg=kind)
            host = page.locator('#view-' + kind)
            host.locator('[class$="-card"]').first.wait_for()
            host.locator('link[href="/workspace.css"]').evaluate('el=>new Promise((resolve,reject)=>{if(el.sheet)resolve();else{el.onload=resolve;el.onerror=reject}})')
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            for dropdown in host.locator('.multi-select').all():
                dropdown.locator('summary').click()
                options = dropdown.locator('.multi-options')
                assert options.evaluate('el=>el.scrollWidth<=el.clientWidth+1'), (width, kind)
                checkbox = options.locator('input[type=checkbox]').first
                if checkbox.count():
                    assert checkbox.bounding_box()['height'] < 30, (width, kind)
                    checkbox.check()
                    assert checkbox.is_checked()
                    checkbox.uncheck()
                dropdown.locator('summary').click()
            if width <= 768:
                page.locator('[data-workspace-target="search"]').click()
                assert host.locator('#keyword').evaluate('el=>el===el.getRootNode().activeElement')
                rect = host.locator('#keyword').bounding_box()
                header = page.locator('.site-header').bounding_box()
                assert rect['y'] >= header['height'] - 1 and rect['y'] < 900
                page.locator('[data-workspace-target="map"]').click()
                assert host.locator('.map-region').evaluate('el=>el===el.getRootNode().activeElement')
                assert abs(host.locator('#map').bounding_box()['y'] - header['height']) < 2
            host.locator('[class$="-card"]').first.click()
            panel = host.locator('#detail-panel')
            panel.wait_for(state='visible')
            rect = panel.bounding_box()
            assert rect['width'] >= min(width - 32, 280), (width, kind, rect)
            assert host.locator('.detail-close').bounding_box()['width'] >= 44
            panel.locator('.detail-close').click()
            if width > 768:
                assert host.locator('#map').bounding_box()['width'] > 200
    page.set_viewport_size({'width': 375, 'height': 900})
    page.screenshot(path='/tmp/midokoro-mobile-after.png')
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.locator('#tab-shiseki').click()
    page.wait_for_function('midokoro.kind==="shiseki"')
    page.screenshot(path='/tmp/midokoro-desktop-after.png')
    assert not errors, errors
    print(json.dumps({'checks': '5 categories × 5 widths, mobile navigation/focus, detail sizing, close, overflow', 'errors': errors}))
    browser.close()
