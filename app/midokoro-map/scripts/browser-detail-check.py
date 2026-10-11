#!/usr/bin/env python3
"""Check shared detail-panel behaviour: reduced motion, live regions, mobile reveal and focus return."""
import json,sys
from playwright.sync_api import sync_playwright
url=sys.argv[1] if len(sys.argv)>1 else "http://127.0.0.1:8533/"
cards={"shiseki":".shiseki-card","omatsuri":".festival-card","onsen":".onsen-card","tokusan":".tokusan-card","geo":".geo-card"}
ACTIVE="k=>{const a=document.querySelector('#view-'+k).shadowRoot.activeElement;return a?(a.id||a.className):null}"
def open_kind(page,kind):
    page.locator("#tab-"+kind).click();page.wait_for_function("k=>midokoro.kind===k",arg=kind)
    page.wait_for_function("k=>Number(document.querySelector('#view-'+k).shadowRoot.querySelector('#result-count').textContent)>0",arg=kind)
    return page.locator("#view-"+kind)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True);errors=[]
    # Desktop with reduced motion: list selection jumps without flyTo/fitBounds animation.
    page=browser.new_context(viewport={"width":1440,"height":960},reduced_motion="reduce").new_page()
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.goto(url,wait_until="domcontentloaded");page.wait_for_function("window.midokoro?.kind")
    for kind,card in cards.items():
        host=open_kind(page,kind)
        page.evaluate("()=>{const m=midokoro.map;m.setView([43,145],5,{animate:false});window.__animated=0;m.off('zoomanim',window.__countAnim);window.__countAnim=()=>window.__animated++;m.on('zoomanim',window.__countAnim)}")
        host.locator(card).first.click();page.wait_for_timeout(300)
        moved=page.evaluate("()=>{const m=midokoro.map;return {lat:m.getCenter().lat,zoom:m.getZoom(),animated:window.__animated+Boolean(m._flyToFrame)+Boolean(m._panAnim?._inProgress)}}")
        assert moved["animated"]==0 and (abs(moved["lat"]-43)>1e-6 or moved["zoom"]!=5),(kind,moved)
        assert host.locator("#detail-panel [aria-live], #detail-content[aria-live]").count()==0,kind
        assert page.evaluate(ACTIVE,kind)=="detail-title",(kind,page.evaluate(ACTIVE,kind))
        host.locator(".detail-close").click()
        assert host.locator(card+"[data-key]").first.evaluate("el=>el.getRootNode().activeElement===el"),kind
        # Removing the selected card while focus is in the panel must not drop focus to body.
        host.locator(card).first.click();host.locator("#detail-title").wait_for()
        host.locator("#detail-title").focus()
        page.evaluate("k=>{const r=document.querySelector('#view-'+k).shadowRoot,i=r.querySelector('#keyword');i.value='zzzz-no-match';i.dispatchEvent(new Event('input',{bubbles:true}))}",kind)
        page.wait_for_timeout(400)
        if host.locator("#detail-panel").is_visible():host.locator(".detail-close").click()
        active=page.evaluate(ACTIVE,kind)
        assert active in {"keyword","map"} or "leaflet-container" in (active or ""),(kind,active)
        host.locator("#clear-filters").click()
    # Phone width: a card far down the list opens a panel that is scrolled into view.
    page=browser.new_context(viewport={"width":390,"height":844},is_mobile=True).new_page()
    page.on("pageerror",lambda e:errors.append(str(e)))
    page.goto(url,wait_until="domcontentloaded");page.wait_for_function("window.midokoro?.kind")
    for kind,card in cards.items():
        host=open_kind(page,kind)
        target=host.locator(card).nth(min(15,host.locator(card).count()-1))
        target.scroll_into_view_if_needed();target.click();host.locator("#detail-title").wait_for()
        page.wait_for_timeout(900)
        top=host.locator("#detail-panel").evaluate("el=>el.getBoundingClientRect().top")
        assert 0<=top<page.viewport_size["height"]*.5,(kind,top)
        host.locator(".detail-close").click()
    browser.close()
print(json.dumps({"checks":"reduced motion, no live detail region, title focus, focus return, removed card, mobile reveal","errors":errors},ensure_ascii=False))
sys.exit(1 if errors else 0)
