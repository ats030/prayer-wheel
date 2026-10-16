#!/usr/bin/env python3
"""Test a genuinely unactivated page under Chromium's normal audio policy."""
import argparse
import time
from playwright.sync_api import sync_playwright


def check(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            '--autoplay-policy=document-user-activation-required',
            '--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies',
        ])

        def fresh_page():
            page = browser.new_page()
            page.route('**/v.js', lambda route: route.abort())
            page.add_init_script('''
              window.playCount = window.wheelCount = 0;
              window.addEventListener('wheel', () => window.wheelCount++, {capture:true});
              const play = HTMLMediaElement.prototype.play;
              HTMLMediaElement.prototype.play = function() {
                window.testAudio = this;
                window.playCount++;
                return play.call(this);
              };
            ''')
            cdp = page.context.new_cdp_session(page)

            def read(expression):
                # Playwright's normal evaluate/locator helpers can grant activation.
                # Every inspection here explicitly avoids manufacturing a gesture.
                result = cdp.send('Runtime.evaluate', {
                    'expression': expression, 'returnByValue': True, 'userGesture': False,
                })
                assert 'exceptionDetails' not in result, result
                return result['result'].get('value')

            def wait(expression):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if read(expression):
                        return
                    time.sleep(.02)
                raise AssertionError('Timed out: ' + expression)

            def center():
                return read('''(() => {
                  const r = document.querySelector('#stage').getBoundingClientRect();
                  return {x:r.x+r.width/2,y:r.y+r.height/2};
                })()''')

            def wheel(delta):
                before = read('wheelCount')
                point = center()
                cdp.send('Input.dispatchMouseEvent', {'type':'mouseMoved', **point})
                cdp.send('Input.dispatchMouseEvent', {
                    'type':'mouseWheel', **point, 'deltaX':0, 'deltaY':delta,
                })
                wait('wheelCount > ' + str(before))

            def click():
                point = center()
                for kind in ('mousePressed', 'mouseReleased'):
                    cdp.send('Input.dispatchMouseEvent', {
                        'type':kind, **point, 'button':'left', 'clickCount':1,
                    })

            page.goto(url)
            wait('document.querySelector("#stage")?.getAttribute("aria-disabled") === "false"')
            return page, cdp, read, wait, wheel, click

        page, cdp, read, wait, wheel, click = fresh_page()
        assert read('navigator.userActivation.hasBeenActive') is False
        assert read('document.querySelector("#currentLine").textContent') == 'タップして開始'
        for delta in (-600, 600, -60):
            wheel(delta)
            assert read('navigator.userActivation.hasBeenActive') is False
            assert read('playCount') == 0
            assert read('document.querySelector("#counter").textContent') == '0'
            assert read('document.querySelector("#queueCount").textContent') == '0'
            assert read('document.querySelector("#voiceBanner").hidden') is True
            assert read('document.querySelector("#stage").dataset.state') == 'ready'
        read('document.querySelector("#stage").click()')
        assert read('playCount') == 0, 'A synthetic click must not unlock startup'
        click()
        wait('window.testAudio && testAudio.currentTime > .15')
        assert read('navigator.userActivation.hasBeenActive') is True
        assert read('playCount') == 1
        assert read('document.querySelector("#counter").textContent') == '1'
        wheel(-60)
        assert read('document.querySelector("#counter").textContent') == '1', 'Pre-start wheel delta leaked'
        wheel(-60)
        wait('document.querySelector("#counter").textContent === "2"')
        wheel(120)
        wait('document.querySelector("#queueCount").textContent === "0"')
        assert read('document.querySelector("#counter").textContent') == '1'
        read('document.querySelector("#restartBtn").click()')
        wheel(-120)
        wait('testAudio.currentTime > .15 && document.querySelector("#counter").textContent === "1"')
        read('document.querySelector("#sutraSelect").value="komyo"; document.querySelector("#sutraSelect").dispatchEvent(new Event("change"))')
        wait('document.querySelector("#stage").getAttribute("aria-disabled") === "false"')
        wheel(-120)
        wait('testAudio.currentTime > .15 && document.querySelector("#counter").textContent === "1"')
        assert read('document.querySelector("#voiceBanner").hidden') is True
        page.reload()
        wait('document.querySelector("#stage").getAttribute("aria-disabled") === "false"')
        wheel(-120)
        assert read('playCount') == 0
        assert read('document.querySelector("#counter").textContent') == '0'
        page.close()

        page, cdp, read, wait, wheel, click = fresh_page()
        assert read('navigator.userActivation.hasBeenActive') is False
        read('document.querySelector("#stage").focus()')
        for kind in ('keyDown', 'keyUp'):
            cdp.send('Input.dispatchKeyEvent', {
                'type':kind, 'key':'Enter', 'code':'Enter', 'windowsVirtualKeyCode':13,
            })
        wait('window.testAudio && testAudio.currentTime > .15')
        assert read('playCount') == 1
        assert read('document.querySelector("#voiceBanner").hidden') is True
        browser.close()
    print('Unactivated page: initial wheels ignored without audio/error/queue; real click/Enter starts audio PASS')
    print('Post-start wheel direction, discarded initial deltas, restart/sutra switch and reload startup gate PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8743/')
    check(parser.parse_args().url)
