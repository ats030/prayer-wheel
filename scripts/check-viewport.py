#!/usr/bin/env python3
"""Verify the wheel remains operable with each drawer open."""
import argparse
from playwright.sync_api import sync_playwright


def check(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.route('**/v.js', lambda route: route.abort())
        for width, height in [(320,568),(375,667),(390,844),(768,1024),(1280,900),(844,390)]:
            page.set_viewport_size({'width':width,'height':height})
            page.goto(url)
            page.wait_for_selector('#stage[aria-disabled="false"]')
            for drawer in ['sutraDetails','settingsDetails','infoDetails']:
                page.locator(f'#{drawer} summary').click()
                page.wait_for_timeout(80)
                result = page.evaluate('''() => {
                  const rect = e => { const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom}; };
                  return {height:innerHeight, width:innerWidth, scroll:document.documentElement.scrollHeight,
                    overflow:document.documentElement.scrollWidth,
                    stage:rect(document.querySelector('#stage')), copy:rect(document.querySelector('.reading-copy')),
                    support:rect(document.querySelector('.support-link')),
                    drawer:rect(document.querySelector('details[open] .drawer-content')),
                    open:document.querySelectorAll('.secondary details[open]').length};
                }''')
                assert result['scroll'] <= height+1, (width,height,drawer,result)
                assert result['overflow'] <= width, (width,height,drawer,result)
                assert result['open']==1, result
                assert result['copy']['x'] + result['copy']['w'] <= result['stage']['x'], ('Wheel must be on the right', result)
                for key in ['stage','copy','support','drawer']:
                    r=result[key]
                    assert r['h']>(60 if key=='stage' else 20) and r['y']>=0 and r['b']<=height, (width,height,drawer,key,result)
                page.locator('#stage').click()
                assert page.locator('#counter').inner_text()!='0'
                page.mouse.wheel(0,500)
                assert page.evaluate('scrollY')==0
            page.locator('#stage').press('Space')
            page.locator('#sutraDetails summary').click()
            page.wait_for_timeout(100)
            page.locator('#textBlock').evaluate('e=>e.scrollTop=e.scrollHeight')
            assert page.locator('#textBlock').evaluate('e=>e.scrollHeight<=e.clientHeight || e.scrollTop>0')
            if width >= 768 and height >= 600 and page.locator('#translationBlock').is_visible():
                gap = page.evaluate("document.querySelector('.support-link').getBoundingClientRect().top - document.querySelector('#translationBlock').getBoundingClientRect().bottom")
                assert 0 <= gap <= 110, ('Excessive space before support', width, height, gap)
            page.screenshot(path=f'/tmp/prayer-wheel-viewport-{width}x{height}.png')
            page.evaluate('''() => {
              document.querySelector('#currentLine').textContent = '観世音菩薩の教えを心に留める。'.repeat(10);
              document.querySelector('#currentTranslation').textContent = '苦しむ人々に寄り添い、心の安らぎへ導きます。'.repeat(10);
              document.querySelector('#translationBlock').hidden = false;
              document.querySelector('#currentTranslation').scrollIntoView({block:'end'});
            }''')
            assert page.evaluate('scrollY')==0
            assert page.locator('#readingCopy').evaluate('e=>e.scrollTop>0')
            page.locator('#stage').click()
            assert page.evaluate('scrollY')==0
            print(f'{width}x{height}: fixed viewport, all drawers, wheel input, internal scroll PASS')
        page.set_viewport_size({'width':568,'height':320})
        page.goto(url)
        page.wait_for_selector('#stage[aria-disabled="false"]')
        page.locator('#sutraDetails summary').click()
        assert page.evaluate('document.documentElement.scrollHeight > innerHeight')
        page.locator('#textBlock').scroll_into_view_if_needed()
        assert page.locator('#textBlock').is_visible()
        page.set_viewport_size({'width':390,'height':667})
        page.goto(url)
        page.wait_for_selector('#stage[aria-disabled="false"]')
        page.locator('#sutraDetails summary').click()
        page.add_style_tag(content='.top, .reading-bottom { font-size: 40px; } .reader-app h1 { font-size: 60px; } .reader-app .support p { font-size: 30px; }')
        page.wait_for_function("document.body.classList.contains('is-constrained')")
        page.locator('#textBlock').scroll_into_view_if_needed()
        assert page.locator('#textBlock').is_visible()
        nojs = browser.new_context(java_script_enabled=False, viewport={'width':390,'height':844})
        fallback = nojs.new_page()
        fallback.goto(url)
        message = fallback.locator('noscript')
        assert message.is_visible()
        assert message.bounding_box()['y'] < 844
        print('Short screen / enlarged text fallback and no-JavaScript message PASS')
        nojs.close()
        browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8743/')
    check(parser.parse_args().url)
