#!/usr/bin/env python3
"""Play all real main WAVs at the UI's maximum rate; verify natural completion."""
import argparse
from playwright.sync_api import sync_playwright


def check(base):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script("""(() => {
          window.completedSections = [];
          const play = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() {
            const section = Number(new URL(this.src).pathname.split('/').pop().split('.')[0]);
            const result = play.call(this);
            result.then(() => this.addEventListener('ended', () => completedSections.push(section), {once:true}));
            return result;
          };
        })();""")
        page.goto(base)
        page.wait_for_selector('#stage[aria-disabled="false"]')
        assert 'VOICEVOX:WhiteCUL' in page.locator('.foot').inner_text()
        count = page.locator('.chunk').count()
        assert count == 29
        page.evaluate('n => window.expectedSections = n', count)
        page.locator('#rate').evaluate("e => { e.value='1.4'; e.dispatchEvent(new Event('input')); }")
        page.locator('#stage').click()
        page.evaluate("""window.fillQueue = setInterval(() => {
          const count = Number(document.querySelector('#counter').textContent);
          const queued = Number(document.querySelector('#queueCount').textContent);
          if (count >= expectedSections) clearInterval(fillQueue);
          else if (queued < 5) document.querySelector('#stage').click();
        }, 100);""")
        for completed in sorted(set([*range(10, count, 10), count])):
            page.wait_for_function('n => completedSections.length >= n', arg=completed, timeout=60000)
            print(f'Completed {completed}/{count} actual WAVs', flush=True)
        assert page.evaluate('completedSections') == list(range(1, count + 1))
        assert page.locator('#rounds').inner_text() == '1'
        assert page.locator('#queueCount').inner_text() == '0'
        assert page.locator('#counter').inner_text() == str(count)
        assert not errors, errors
        browser.close()
        print(f'All {count} phrases completed in order using real media ended events; one full cycle PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://prayer-wheel.ats030.workers.dev')
    check(parser.parse_args().url)
