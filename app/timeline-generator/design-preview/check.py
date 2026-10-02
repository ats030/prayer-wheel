"""Validate only the isolated comparison preview; no live generation calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
URL = 'http://ubuntu-server-app:8533/'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    errors, api_calls, metrics = [], [], {}
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: api_calls.append(r.url) if '/api/jobs/' in r.url else None)
    for view in ['current', 'proposal']:
        for width in [320, 375, 414, 768, 1280]:
            page.set_viewport_size({'width':width, 'height':900})
            page.goto(URL+f'?view={view}&count=100')
            page.wait_for_function('document.querySelectorAll(".event").length === 100')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (view,width)
            assert page.locator('blockquote, .event-quote, .evidence, .context-heading').count()==0
            assert not page.locator('#generation-info').evaluate('(el)=>el.open')
            assert page.locator('.event > .source-link').evaluate_all('(els)=>els.every(el=>el.getBoundingClientRect().height>=44)')
            assert page.locator('.event-description').evaluate_all('(els)=>els.every(el=>el.scrollHeight<=el.clientHeight && getComputedStyle(el).textOverflow!=="ellipsis")')
        for width in [320,1280]:
            page.set_viewport_size({'width':width,'height':900})
            page.evaluate('document.documentElement.style.fontSize="200%"')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('zoom',view,width)
        page.set_viewport_size({'width':1280,'height':900})
        page.goto(URL+f'?view={view}')
        page.wait_for_selector('.event')
        metrics[view]=page.locator('.event').evaluate_all('(els)=>({count:els.length,average_height:els.reduce((s,e)=>s+e.getBoundingClientRect().height,0)/els.length,visible:els.filter(e=>e.getBoundingClientRect().bottom<=innerHeight).length,first_top:els[0].getBoundingClientRect().top})')
        page.screenshot(path=str(ROOT/f'{view}-desktop.png'))
    assert metrics['proposal']['average_height'] <= metrics['current']['average_height']*1.1
    assert metrics['proposal']['visible'] >= metrics['current']['visible']
    for state in ['running','partial','failed','empty']:
        page.goto(URL+f'?state={state}')
        page.wait_for_function('document.getElementById("job-status").textContent !== ""')
        if state=='running':
            assert page.locator('#progress').is_visible() and page.locator('#old-result').is_visible()
        elif state=='partial': assert page.locator('#result-notice').is_visible()
        elif state=='failed':
            assert page.locator('#page-error').is_visible() and page.locator('#old-result').is_visible()
            page.locator('#retry').click()
            page.wait_for_function('document.getElementById("job-status").textContent === "生成中"')
            page.wait_for_function('document.getElementById("job-status").textContent === "完了"',timeout=10000)
        else: assert page.locator('#result-empty').is_visible() and page.locator('.event').count()==0
    page.goto(URL)
    page.locator('#generation-info summary').focus()
    page.keyboard.press('Enter')
    assert page.locator('#generation-info').evaluate('(el)=>el.open')
    assert page.locator('#generation-info summary').evaluate('(el)=>getComputedStyle(el).outlineStyle !== "none"')
    page.locator('#preview-view').select_option('current')
    page.wait_for_function('document.body.dataset.view === "current"')
    page.set_viewport_size({'width':375,'height':900})
    page.goto(URL+'?view=proposal')
    page.wait_for_selector('.event')
    page.screenshot(path=str(ROOT/'proposal-mobile.png'),full_page=True)
    assert not errors, errors
    assert not api_calls, api_calls
    (ROOT/'checks.json').write_text(json.dumps({'widths':[320,375,414,768,1280],'events':100,'text_zoom':'200%','states':['complete','running','partial','failed','empty'],'keyboard':'Enter/details/focus-visible and native view selector','page_errors':errors,'network_api_calls':api_calls,'saved_fixture':metrics},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(metrics,ensure_ascii=False))
    browser.close()
