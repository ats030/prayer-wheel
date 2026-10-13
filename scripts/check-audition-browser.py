#!/usr/bin/env python3
"""Verify actual A/B playback, exclusive switching, completion, error and mobile layout."""
import argparse
from playwright.sync_api import sync_playwright


def check(base):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for width in (375, 1280):
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base.rstrip('/') + '/audition/')
            page.wait_for_function("[...document.querySelectorAll('audio')].every(a => a.readyState >= 1)")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#currentAudio').evaluate('(a) => a.play()')
            page.wait_for_function('currentAudio.currentTime > 0.2 && !currentAudio.paused')
            page.locator('#adjustedAudio').evaluate('(a) => a.play()')
            page.wait_for_function('adjustedAudio.currentTime > 0.2 && !adjustedAudio.paused && currentAudio.paused')
            page.locator('#adjustedAudio').evaluate('(a) => a.pause()')
            page.wait_for_function("document.querySelector('#auditionStatus').textContent.includes('一時停止')")
            page.locator('#adjustedAudio').evaluate('(a) => { a.currentTime = a.duration - 0.3; return a.play(); }')
            page.wait_for_function('adjustedAudio.ended')
            page.wait_for_function("document.querySelector('#auditionStatus').textContent.includes('終わりました')")
            assert not errors, errors
            page.close()
        page = browser.new_page()
        page.route('**/adjusted.wav', lambda route: route.abort())
        page.goto(base.rstrip('/') + '/audition/')
        page.wait_for_function("document.querySelector('#auditionStatus').textContent.includes('読み込めませんでした')")
        browser.close()
        print('Browser verified: real A/B playback, exclusive switching, pause/end/error, 375/1280px layout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://prayer-wheel.ats030.workers.dev')
    check(parser.parse_args().url)
