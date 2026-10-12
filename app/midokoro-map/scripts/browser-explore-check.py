#!/usr/bin/env python3
"""Regional exploration against real lists and existing detail renderers."""
import json
import sys
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8533/'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 960}, reduced_motion='reduce')
    context.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url, wait_until='domcontentloaded')
    page.wait_for_function('window.midokoro?.kind==="explore"')
    host = page.locator('#view-explore')
    page.wait_for_function('Number(document.querySelector("#view-explore").shadowRoot.querySelector("#result-count").textContent)>25000')
    assert host.locator('#explore-status').inner_text() == ''
    first_kinds = host.locator('.result-kind').all_text_contents()[:5]
    assert len(set(first_kinds)) == 5, first_kinds
    host.locator('#prefecture').select_option('熊本県')
    regional = int(host.locator('#result-count').inner_text())
    assert 50 < regional < 1000, regional
    assert all('熊本県' in value for value in host.locator('.card-meta').all_text_contents())
    point = page.evaluate('({center:midokoro.map.getCenter(),zoom:midokoro.map.getZoom()})')
    for kind in ['shiseki', 'omatsuri', 'onsen', 'tokusan', 'geo']:
        host.locator('#category').select_option(kind)
        card = host.locator('.explore-card').first
        card.wait_for()
        name = card.locator('.card-name').inner_text()
        card.click()
        dialog = page.locator('#explore-detail')
        dialog.wait_for(state='visible')
        assert page.locator('#explore-detail #detail-title').inner_text() == name
        assert page.locator('#explore-detail #detail-title').evaluate('el=>el===el.getRootNode().activeElement')
        # Native modal blocks the search underneath and keeps keyboard focus inside.
        page.keyboard.press('Tab')
        assert page.evaluate('document.activeElement.closest("#explore-detail")!==null')
        page.keyboard.press('Escape')
        dialog.wait_for(state='hidden')
        assert card.evaluate('el=>el===el.getRootNode().activeElement'), kind
        restored = page.evaluate('({center:midokoro.map.getCenter(),zoom:midokoro.map.getZoom()})')
        assert restored == point, (kind, restored, point)
    # Programmatic navigation during a modal must not resurrect its selection on return.
    host.locator('.explore-card').first.click()
    page.locator('#explore-detail').wait_for(state='visible')
    page.evaluate('document.querySelector("#tab-onsen").click()')
    page.wait_for_function('midokoro.kind==="onsen"')
    page.locator('#tab-explore').click()
    page.wait_for_function('midokoro.kind==="explore"')
    assert 'item=' not in page.url
    assert host.locator('.explore-card[aria-current=true]').count() == 0
    host.locator('#category').select_option('geo')
    host.locator('#keyword').fill('阿蘇くじゅう')
    card = host.locator('.explore-card').first
    assert '範囲' in card.inner_text()
    assert int(host.locator('#result-count').inner_text()) == 1
    card.click()
    page.locator('#explore-detail').wait_for(state='visible')
    assert page.locator('#explore-detail .detail-links a').count() >= 2
    shared = page.url
    page.reload(wait_until='domcontentloaded')
    page.locator('#explore-detail').wait_for(state='visible')
    assert '阿蘇くじゅう' in page.locator('#explore-detail #detail-title').inner_text()
    page.locator('#explore-detail .detail-close').click()
    assert 'item=' not in page.url
    host.locator('#clear-filters').click()
    page.evaluate('()=>{midokoro.map.setView([32.9,131.1],10,{animate:false})}')
    host.locator('#search-area').click()
    count = int(host.locator('#result-count').inner_text())
    assert 0 < count < 1000, count
    assert 'bounds=' in page.url and host.locator('#clear-area').is_visible()
    before = host.locator('.card-name').all_text_contents()
    page.evaluate('()=>{midokoro.map.setView([43,145],10,{animate:false})}')
    assert host.locator('.card-name').all_text_contents() == before
    host.locator('#search-area').click()
    assert host.locator('.card-name').all_text_contents() != before
    host.locator('#clear-area').click()
    assert int(host.locator('#result-count').inner_text()) > 25000
    host.locator('#keyword').fill('zzzz-no-regional-result')
    assert host.locator('#explore-empty').is_visible()
    host.locator('#clear-filters').click()
    # Search state survives a trip to the category-specific filters.
    host.locator('#prefecture').select_option('群馬県')
    host.locator('#category').select_option('onsen')
    host.locator('#keyword').fill('草津')
    saved = host.locator('#result-count').inner_text()
    page.locator('#tab-shiseki').click()
    page.wait_for_function('midokoro.kind==="shiseki"')
    page.locator('#tab-explore').click()
    page.wait_for_function('midokoro.kind==="explore"')
    assert host.locator('#prefecture').input_value() == '群馬県'
    assert host.locator('#keyword').input_value() == '草津'
    assert host.locator('#result-count').inner_text() == saved
    assert 'prefecture=' in page.url
    for width in [320, 375, 768, 900, 1440]:
        page.set_viewport_size({'width': width, 'height': 960})
        for size in ['100%', '200%']:
            page.evaluate('value=>document.documentElement.style.fontSize=value', size)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), (width, size)
            assert host.locator('#map').bounding_box()['width'] > 200
            host.locator('.explore-card').first.click()
            page.locator('#explore-detail').wait_for(state='visible')
            panel = page.locator('#explore-detail #detail-panel')
            assert panel.evaluate('el=>el.scrollWidth<=el.clientWidth+1'), (width, size)
            page.keyboard.press('Escape')
        page.evaluate('document.documentElement.style.fontSize="100%"')
        if width <= 768:
            assert host.locator('#mobile-prefecture').is_visible()
            host.locator('#mobile-prefecture').select_option('群馬県')
            assert host.locator('#prefecture').input_value() == '群馬県'
            page.locator('[data-workspace-target="search"]').click()
            assert host.locator('#keyword').evaluate('el=>el===el.getRootNode().activeElement')
            page.locator('[data-workspace-target="map"]').click()
            assert host.locator('.map-region').evaluate('el=>el===el.getRootNode().activeElement')
    page.set_viewport_size({'width': 1440, 'height': 960})
    page.screenshot(path='/tmp/midokoro-explore-desktop.png')
    page.set_viewport_size({'width': 375, 'height': 960})
    page.screenshot(path='/tmp/midokoro-explore-mobile.png')
    # A failed dataset stays explicit, while successful categories are still usable.
    failed_context = browser.new_context()
    failed_context.route('**/api/onsen/onsen/', lambda route: route.fulfill(status=503, body='unavailable'))
    failed_context.route('https://*.tile.openstreetmap.org/**', lambda route: route.abort())
    failed = failed_context.new_page()
    failed.goto(urljoin(url, '?kind=explore'), wait_until='domcontentloaded')
    failed_host = failed.locator('#view-explore')
    failed_host.locator('#explore-retry').wait_for(state='visible')
    assert '温泉' in failed_host.locator('#explore-status').inner_text()
    failed_host.locator('#category').select_option('onsen')
    assert failed_host.locator('#result-count').inner_text() == '0'
    failed_context.unroute('**/api/onsen/onsen/')
    failed_host.locator('#explore-retry').click()
    page_errors = []
    failed.on('pageerror', lambda error: page_errors.append(str(error)))
    failed_host.locator('#explore-retry').wait_for(state='hidden')
    failed.wait_for_function('Number(document.querySelector("#view-explore").shadowRoot.querySelector("#result-count").textContent)>1000')
    assert not errors and not page_errors, (errors, page_errors)
    print(json.dumps({'regional_count': regional, 'checks': '5 categories, prefecture, keyword, viewport search, detail reuse/focus/Escape, URL restoration, per-view state, 5 widths/200%, mobile jumps, partial failure/retry', 'errors': errors}, ensure_ascii=False))
    browser.close()
