#!/usr/bin/env python3
"""Measure rendered rotation across real queued audio boundaries."""
import argparse
from playwright.sync_api import sync_playwright


def check(base):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.route('**/v.js', lambda route: route.abort())
        page.add_init_script('''
          const play = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() {
            window.testAudio = this;
            window.testPlayCount = (window.testPlayCount || 0) + 1;
            return play.call(this);
          };
        ''')
        for sutra in ('hannya', 'enmei', 'komyo', 'hachidai', 'amida'):
            page.goto(base)
            page.wait_for_selector('#stage[aria-disabled="false"]')
            if sutra != 'hannya':
                page.select_option('#sutraSelect', sutra)
                page.wait_for_selector('#stage[aria-disabled="false"]')
            page.locator('#stage').click()
            page.locator('#stage').press('ArrowDown')
            page.locator('#stage').press('ArrowDown')
            page.wait_for_function('testAudio.currentTime > .2')
            result = page.evaluate('''async () => {
              const dial = document.querySelector('#dial');
              const sources = new Set();
              let previous = '', lastChange = performance.now(), lastFrame = lastChange;
              let maxHold = 0;
              const started = lastChange;
              await new Promise((resolve, reject) => {
                function sample(now) {
                  sources.add(testAudio.src + "|" + window.testPlayCount);
                  const transform = getComputedStyle(dial).transform;
                  if (now - lastFrame > 50) lastChange = now;
                  if (transform !== previous) {
                    maxHold = Math.max(maxHold, now - lastChange);
                    previous = transform;
                    lastChange = now;
                  }
                  lastFrame = now;
                  if (sources.size >= 3 && testAudio.currentTime > .25) resolve();
                  else if (now - started > 25000) reject(Error('Queued sections did not play'));
                  else requestAnimationFrame(sample);
                }
                requestAnimationFrame(sample);
              });
              return {sources: sources.size, prepared: [...sources].filter(s => s.startsWith('blob:')).length, maxHold};
            }''')
            assert result['sources'] >= 3, result
            assert result['prepared'] >= 2, ('Queued audio was not prepared', sutra, result)
            assert result['maxHold'] < 65, (sutra, result)
            assert page.evaluate('''() => {
              const dial = document.querySelector('#dial');
              const before = getComputedStyle(dial).transform;
              document.querySelector('#stage').dispatchEvent(new KeyboardEvent('keydown', {code: 'Space', bubbles: true}));
              return before === getComputedStyle(dial).transform;
            }'''), 'Pause jumped to the interpolation target'
            frozen = page.locator('#dial').evaluate('e => getComputedStyle(e).transform')
            page.wait_for_timeout(200)
            assert page.locator('#dial').evaluate('e => getComputedStyle(e).transform') == frozen
            page.locator('#stage').press('ArrowUp')
            assert page.locator('#dial').evaluate('e => getComputedStyle(e).transform') == frozen, 'Paused reverse moved the drum'
            page.locator('#stage').press('Space')
            page.wait_for_function("document.querySelector('#dial').dataset.moving === 'true'")
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function("document.querySelector('#dial').dataset.moving === 'false'")
            assert page.locator('#dial').evaluate('e => getComputedStyle(e).transitionDuration') == '0s'
            page.emulate_media(reduced_motion='no-preference')
            page.wait_for_function("document.querySelector('#dial').dataset.moving === 'true'")
            assert page.evaluate('''() => {
              const dial = document.querySelector('#dial');
              const before = getComputedStyle(dial).transform;
              testAudio.dispatchEvent(new Event('waiting'));
              return before === getComputedStyle(dial).transform && dial.dataset.moving === 'false';
            }'''), 'Waiting did not freeze the rendered position'
            page.wait_for_function("document.querySelector('#dial').dataset.moving === 'true'")
            page.wait_for_function('testAudio.ended', timeout=15000)
            page.wait_for_timeout(200)
            assert page.locator('#dial').evaluate('''e => {
              const matrix = new DOMMatrixReadOnly(getComputedStyle(e).transform);
              const radians = -parseFloat(e.style.getPropertyValue('--drum-turn')) * Math.PI / 180;
              return !e.style.transform && Math.abs(matrix.m22 - Math.cos(radians)) < .00001
                && Math.abs(matrix.m23 - Math.sin(radians)) < .00001;
            }'''), 'Normal completion did not settle at its target'
            print(f'{sutra}: two audio boundaries, longest unchanged frame interval {result["maxHold"]:.1f}ms; pause/reduced motion/waiting recovery PASS')
        browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8743/')
    check(parser.parse_args().url)
