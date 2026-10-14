#!/usr/bin/env python3
"""Check optional support rendering and browser layout without making payments."""
import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('support_link', ROOT / 'scripts/support-link.py')
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


def check():
    source = (ROOT / 'index.html').read_text()
    assert support.render(source, {'url': None, 'usageConfirmed': False}) == source
    for config in ({'url': 'https://example.com/support', 'usageConfirmed': False},
                   {'url': 'javascript:alert(1)', 'usageConfirmed': True},
                   {'url': 'http://example.com', 'usageConfirmed': True},
                   {'url': 'https://user:pass@example.com', 'usageConfirmed': True},
                   {'url': 'https://@example.com', 'usageConfirmed': True},
                   {'url': 'https://example.com:99999', 'usageConfirmed': True},
                   {'url': 'https://example.com/\x7f', 'usageConfirmed': True},
                   {'url': 'https://example.com/\n', 'usageConfirmed': True}):
        try:
            support.render(source, config)
        except ValueError:
            pass
        else:
            raise AssertionError(config)
    enabled = support.render(source, {'url': 'https://example.com/?a=1&b="test"', 'usageConfirmed': True})
    assert 'class="support" hidden' not in enabled
    assert 'href="https://example.com/?a=1&amp;b=&quot;test&quot;"' in enabled
    for changed in (source.replace('class="support" hidden', 'hidden class="support"'),
                    source.replace('class="btn support-link"', 'class="support-link btn"')):
        try:
            support.render(changed, {'url': 'https://example.com', 'usageConfirmed': True})
        except ValueError:
            pass
        else:
            raise AssertionError('Changed template was not rejected')
    print('Support rendering: hidden default, eligibility gate, HTTPS and escaped URL PASS')


def browser_check(base):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.route('**/v.js', lambda route: route.abort())
        source = (ROOT / 'index.html').read_text()
        page.route(base.rstrip('/') + '/', lambda route: route.fulfill(body=support.render(source, {'url': None}), content_type='text/html'))
        page.goto(base)
        assert page.locator('.support').is_hidden()
        page.unroute(base.rstrip('/') + '/')
        enabled = support.render(source, {'url': 'https://example.com/support', 'usageConfirmed': True})
        page.route(base.rstrip('/') + '/', lambda route: route.fulfill(body=enabled, content_type='text/html'))
        for width in (320, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(base)
            page.wait_for_selector('#stage[aria-disabled="false"]')
            link = page.locator('.support-link')
            assert link.is_visible()
            assert link.get_attribute('href') == 'https://example.com/support'
            assert link.get_attribute('target') == '_blank'
            assert set(link.get_attribute('rel').split()) >= {'noopener', 'noreferrer'}
            link.focus()
            assert link.evaluate('e => e === document.activeElement')
            assert link.evaluate('e => getComputedStyle(e).outlineStyle') != 'none'
            assert page.evaluate('document.documentElement.scrollWidth') <= width
            bounds = link.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
            if width == 320:
                page.screenshot(path='/tmp/prayer-wheel-support-mobile.png', full_page=True)
        page.context.route('https://example.com/**', lambda route: route.fulfill(body='Support destination test', content_type='text/html'))
        with page.expect_popup() as popup:
            page.locator('.support-link').press('Enter')
        popup.value.wait_for_load_state()
        assert popup.value.url == 'https://example.com/support'
        popup.value.close()
        assert page.locator('#stage').is_visible()
        browser.close()
        print('Support UI: hidden default; enabled 320/1280px, focus and keyboard new tab PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    args = parser.parse_args()
    check()
    if args.url:
        browser_check(args.url)
