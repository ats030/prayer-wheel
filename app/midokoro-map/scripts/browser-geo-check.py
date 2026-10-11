#!/usr/bin/env python3
"""Geo category visibility, state, accessibility and retry with the real Leaflet map."""
import json,sys
from pathlib import Path
from playwright.sync_api import sync_playwright
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18533/'
root=Path(__file__).resolve().parents[1]
expected={name:len(json.loads((root/'frontend/geo'/f'{name}.json').read_text())['features']) for name in ['geoparks','geosites']}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':960})
    page=context.new_page(); errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    # Basemap failure does not obscure data-layer checks or incur external requests.
    context.route('https://*.tile.openstreetmap.org/**',lambda route:route.abort())
    page.goto(url,wait_until='domcontentloaded')
    page.wait_for_function("window.midokoro?.kind==='shiseki'")
    assert page.locator('#view-shiseki .leaflet-control-layers').count()==0
    page.evaluate('midokoro.map.setView([32.8,130.7],9,{animate:false})')
    page.locator('#tab-geo').click()
    page.wait_for_function("window.midokoro?.kind==='geo'")
    host=page.locator('#view-geo')
    page.wait_for_function("n=>Number(document.querySelector('#view-geo').shadowRoot.querySelector('#result-count').textContent)===n",arg=sum(expected.values()))
    position=page.evaluate('({lat:midokoro.map.getCenter().lat,lng:midokoro.map.getCenter().lng,zoom:midokoro.map.getZoom()})')
    assert abs(position['lat']-32.8)<1e-8 and abs(position['lng']-130.7)<1e-8 and position['zoom']==9,position
    assert host.locator('.geo-card').count()==sum(expected.values())
    host.locator('#geo-type').select_option('geosite')
    assert int(host.locator('#result-count').inner_text())==expected['geosites']
    assert page.evaluate('()=>{let count=0;midokoro.map.eachLayer(layer=>{if(layer instanceof L.CircleMarker)count++});return count}')==expected['geosites']
    host.locator('.geo-card').first.click()
    host.locator('.leaflet-popup-content').wait_for()
    source=host.locator('.leaflet-popup-content a').first
    assert source.get_attribute('target')=='_blank'
    assert 'noopener' in source.get_attribute('rel')
    assert '指定基準' in host.locator('.leaflet-popup-content').inner_text()
    host.locator('#geo-type').select_option('geopark')
    assert int(host.locator('#result-count').inner_text())==expected['geoparks']
    host.locator('.geo-card').first.click()
    host.locator('.leaflet-popup-content').filter(has_text='構成自治体').wait_for()
    assert '構成自治体' in host.locator('.leaflet-popup-content').filter(has_text='構成自治体').inner_text()
    host.locator('#clear-filters').click()
    host.locator('#keyword').fill('熊本')
    filtered=host.locator('#result-count').inner_text()
    assert 0<int(filtered)<sum(expected.values())
    page.evaluate('midokoro.map.setView([32.8,130.7],9,{animate:false})')
    for kind in ['shiseki','omatsuri','onsen','tokusan']:
        page.locator('#tab-'+kind).click()
        page.wait_for_function("kind=>midokoro.kind===kind",arg=kind)
        assert page.evaluate('()=>{let count=0;midokoro.map.eachLayer(layer=>{if(layer.feature?.properties?.heritage_id || layer.feature?.properties?.slug)count++});return count}')==0,kind
        assert page.locator('#view-'+kind+' .leaflet-control-layers').count()==0
    page.locator('#tab-geo').click();page.wait_for_function("midokoro.kind==='geo'")
    assert host.locator('#keyword').input_value()=='熊本'
    assert host.locator('#result-count').inner_text()==filtered
    assert page.evaluate('midokoro.map.getZoom()')==9
    host.locator('#keyword').fill('zzzz-no-geo-results')
    assert host.locator('#geo-empty').is_visible()
    assert host.locator('.geo-card').count()==0
    host.locator('#clear-filters').click()
    for width in [320,375,414,768,1440]:
        page.set_viewport_size({'width':width,'height':960})
        for zoom in [100,200]:
            page.evaluate('(zoom)=>document.documentElement.style.fontSize=zoom+"%"',zoom)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),(width,zoom)
            assert page.evaluate('()=>[...document.querySelectorAll("[role=tab]")].every(tab=>{const bounds=tab.getBoundingClientRect(),range=document.createRange();range.selectNodeContents(tab);return [...range.getClientRects()].every(rect=>rect.left>=bounds.left-1&&rect.right<=bounds.right+1&&rect.right<=innerWidth+1)})'),("tab label",width,zoom)
            rect=host.locator('#map').bounding_box()
            assert rect and rect['width']>200 and rect['height']>200,(width,zoom,rect)
        page.evaluate('document.documentElement.style.fontSize="100%"')
    page.locator('#tab-geo').focus();page.keyboard.press('Home')
    page.wait_for_function("midokoro.kind==='shiseki'")
    page.keyboard.press('End');page.wait_for_function("midokoro.kind==='geo'")
    assert page.locator('#tab-geo').evaluate('element=>element===document.activeElement')
    page.reload();page.wait_for_function("window.midokoro?.kind==='geo'")
    page.goto(url+'?kind=geo',wait_until='domcontentloaded')
    page.wait_for_function("window.midokoro?.kind==='geo'")
    # Dataset failure is recoverable without reloading or a second map.
    failures=[True]
    def fail_once(route):
        if failures[0]:
            route.fulfill(status=503,content_type='application/json',body='{}')
        else: route.continue_()
    context.route('**/geo/geosites.json',fail_once)
    page.reload();page.wait_for_function("window.midokoro?.kind==='geo'")
    host=page.locator('#view-geo')
    host.locator('#geo-retry').wait_for()
    failures[0]=False
    host.locator('#geo-retry').click()
    page.wait_for_function("n=>Number(document.querySelector('#view-geo').shadowRoot.querySelector('#result-count').textContent)===n",arg=sum(expected.values()))
    assert host.locator('#geo-retry').is_hidden()
    for width in [320,1440]:
        page.set_viewport_size({'width':width,'height':960})
        page.screenshot(path=f'/tmp/midokoro-geo-{width}.png',full_page=True)
    assert page.locator('.leaflet-container').count()==1
    assert not errors,errors
    browser.close()
print(json.dumps({'expected':expected,'checks':'isolated geo layers, shared map position, filters, all natural monuments, sources, revisit/URL/keyboard, empty/retry, 5 widths/200%','errors':errors},ensure_ascii=False))
