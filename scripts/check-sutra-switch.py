#!/usr/bin/env python3
"""Check real playback, reset, race handling and failures when selecting sutras."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def check(base, sutra_id='enmei'):
    source = json.loads((ROOT / f'data/{sutra_id}.json').read_text())
    count = len(source['chunks'])
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        context.route('**/v.js', lambda route: route.abort())
        context.add_init_script('''
          const play = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() { window.testAudio = this; return play.call(this); };
        ''')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def ready():
            page.wait_for_selector('#stage[aria-disabled="false"]')

        def select(value):
            page.select_option('#sutraSelect', value)
            ready()

        page.goto(base)
        ready()
        assert page.locator('#sutraSelect option').evaluate_all("items => items.map(e => e.value)") == ['hannya','enmei','rokuji','komyo']
        page.locator('#stage').tap()
        page.wait_for_function('window.testAudio && testAudio.currentTime > .3')
        page.locator('#stage').tap()
        assert page.locator('#queueCount').text_content() == '1'
        select(sutra_id)
        assert page.locator('#sutraName').inner_text() == source['title']
        assert page.locator('#textBlock .chunk').count() == count
        assert page.locator('#counter').text_content() == '0'
        assert page.locator('#queueCount').text_content() == '0'
        assert page.locator('#translationBlock').is_hidden()
        assert page.evaluate('testAudio.paused && !testAudio.getAttribute("src")')
        page.evaluate('testAudio.dispatchEvent(new Event("ended"))')
        assert page.locator('#rounds').text_content() == '0'
        page.locator('#stage').tap()
        page.wait_for_function('testAudio.currentTime > .4')
        assert page.locator('#currentLine').inner_text() == source['chunks'][0]['text']
        assert page.locator('#currentTranslation').inner_text() == source['chunks'][0]['translation']
        assert page.locator('.translation-label').inner_text() == source.get('translationLabel', '現代語訳（意訳）')
        assert page.locator('.reel-face.is-selected').get_attribute('data-section') == '0'
        page.screenshot(path=f'/tmp/prayer-wheel-{sutra_id}-mobile.png', full_page=True)
        # A switch while audio is playing must detach the previous player.
        select('hannya')
        assert page.locator('#textBlock .chunk').count() == 29
        assert page.evaluate('testAudio.paused && !testAudio.getAttribute("src")')
        assert page.locator('#translationBlock').is_hidden()

        # An aborted old load must never overwrite a newer selection.
        held = []
        page.route(f'**/data/{sutra_id}-timing.json', lambda route: held.append(route))
        page.select_option('#sutraSelect', sutra_id)
        page.wait_for_timeout(100)
        assert held, 'The delayed old load must actually be intercepted'
        assert page.locator('#stage').get_attribute('aria-disabled') == 'true'
        select('hannya')
        for route in held:
            try:
                route.abort()
            except Exception:
                pass  # The selection's AbortController may already have cancelled it.
        page.unroute(f'**/data/{sutra_id}-timing.json')
        assert page.locator('#sutraName').inner_text() == '般若心経'
        assert page.locator('#textBlock .chunk').count() == 29
        assert page.locator('#voiceBanner').is_hidden()

        # Retrying a failed load must retry the selected sutra, not the default.
        page.route(f'**/data/{sutra_id}-timing.json', lambda route: route.fulfill(status=503, body='unavailable'))
        page.select_option('#sutraSelect', sutra_id)
        page.wait_for_selector('#reloadBtn:visible')
        assert page.locator('#stage').get_attribute('aria-disabled') == 'true'
        assert page.locator('#textBlock .chunk').count() == 0
        assert page.evaluate('!testAudio.getAttribute("src")')
        page.unroute(f'**/data/{sutra_id}-timing.json')
        page.locator('#reloadBtn').click()
        ready()
        assert page.locator('#sutraSelect').input_value() == sutra_id
        assert page.locator('#textBlock .chunk').count() == count
        assert page.locator('#voiceBanner').is_hidden()

        # Exercise all source/translation/character mappings at each width.
        page.emulate_media(reduced_motion='reduce')
        for width in (320, 375, 414, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            page.locator('#settingsDetails').evaluate('e => e.open = true')
            page.locator('#restartBtn').click()
            assert page.locator('#translationBlock').is_hidden()
            result = page.evaluate('''(count) => {
              const translations = [];
              const failures = [];
              for (let i = 0; i < count; i++) {
                document.getElementById('stage').click();
                testAudio.dispatchEvent(new Event('playing'));
                const current = document.getElementById('currentTranslation');
                translations.push([document.getElementById('currentLine').textContent, current.textContent]);
                const text = current.getBoundingClientRect();
                const support = document.querySelector('.support-link').getBoundingClientRect();
                if (text.left < 0 || text.right > innerWidth || text.bottom > support.top) failures.push(i);
                if (document.querySelector('.reel-face.is-selected').dataset.section !== String(i)) failures.push('cue-'+i);
                testAudio.dispatchEvent(new Event('ended'));
              }
              return {translations, failures, width: document.documentElement.scrollWidth};
            }''', count)
            assert result['translations'] == [[c['text'], c['translation']] for c in source['chunks']]
            assert not result['failures'], (width, result['failures'])
            assert result['width'] <= width
            assert page.locator('#rounds').text_content() == '1'
            assert page.locator('.support-link').get_attribute('href') == 'https://buymeacoffee.com/ats030'
        assert not errors, errors
        browser.close()
    print('Sutra selection: real WAVs, old audio/queue reset, stale events, last selection wins, retry selected source PASS')
    print(f"{source['title']}: all {count} text/meaning/character sections, cycle count and layout at five widths PASS")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8743')
    parser.add_argument('--sutra', choices=['enmei','rokuji','komyo'], default='enmei')
    args = parser.parse_args()
    check(args.url, args.sutra)
