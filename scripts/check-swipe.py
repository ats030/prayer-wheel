#!/usr/bin/env python3
"""Exercise real touchscreen swipes, native clicks and scroll ownership."""
import argparse
import time
from playwright.sync_api import sync_playwright


def check(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--autoplay-policy=document-user-activation-required'])
        context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
        context.route('**/v.js', lambda route: route.abort())
        context.add_init_script('''
          window.playCount = 0;
          const play = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() {
            window.testAudio = this; window.playCount++; return play.call(this);
          };
        ''')
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        cdp = context.new_cdp_session(page)

        def read(expression):
            result = cdp.send('Runtime.evaluate', {
                'expression':expression, 'returnByValue':True, 'userGesture':False,
            })
            assert 'exceptionDetails' not in result, result
            return result['result'].get('value')

        def wait(expression):
            until = time.monotonic() + 10
            while time.monotonic() < until:
                if read(expression): return
                time.sleep(.02)
            raise AssertionError('Timed out: ' + expression)

        def point(selector='#stage'):
            return read('''(() => {
              const r=document.querySelector(''' + repr(selector) + ''').getBoundingClientRect();
              return {x:r.x+r.width/2,y:r.y+r.height/2};
            })()''')

        def send(kind, points):
            cdp.send('Input.dispatchTouchEvent', {'type':kind, 'touchPoints':points})

        def finger(p, identifier=1):
            return {**p, 'id':identifier, 'radiusX':2, 'radiusY':2, 'force':1}

        def swipe(dy, dx=0, origin=None, cancel=False):
            p = origin or point()
            send('touchStart', [finger(p)])
            for step in range(1, 9):
                send('touchMove', [finger({'x':p['x']+dx*step/8,'y':p['y']+dy*step/8})])
                time.sleep(.015)
            send('touchCancel' if cancel else 'touchEnd', [])
            time.sleep(.1)  # Include any compatibility click in the assertions.

        def tap():
            send('touchStart', [finger(point())]); send('touchEnd', [])
            time.sleep(.05)

        def counts():
            return read('[Number(document.querySelector("#counter").textContent),Number(document.querySelector("#queueCount").textContent)]')

        def reset():
            read('document.querySelector("#restartBtn").click()')
            tap()
            wait('window.testAudio && testAudio.currentTime > .1')
            assert counts() == [1, 0], counts()

        page.goto(url)
        wait('document.querySelector("#stage")?.getAttribute("aria-disabled") === "false"')
        assert read('navigator.userActivation.hasBeenActive') is False
        swipe(-100)
        assert counts() == [0, 0] and read('playCount') == 0
        assert read('document.querySelector("#voiceBanner").hidden') is True
        tap()
        wait('window.testAudio && testAudio.currentTime > .1')
        assert counts() == [1, 0], 'A swipe before startup must not leak a click'
        swipe(-260)
        assert counts() == [2, 1], ('Long swipe must be exactly one operation', counts())
        tap()
        assert counts() == [3, 2], 'A real tap immediately after swipe must still work'
        before = counts()
        swipe(-20)
        assert counts() == before, 'Short drag must not become a tap'
        swipe(0, -80)
        assert counts() == before, 'Horizontal gesture must not turn the drum'
        swipe(-80, cancel=True)
        assert counts() == before, 'Canceled gesture must not turn the drum'
        tap()
        assert counts() == [4, 3], 'Tap after cancellation must work'

        reset()
        swipe(-80); swipe(-80)
        read('testAudio.dispatchEvent(new Event("ended"))')
        wait('document.querySelector("#currentLine").textContent === "観自在菩薩"')
        assert counts() == [3, 1], counts()
        swipe(100)
        wait('document.querySelector("#currentLine").textContent === "摩訶般若波羅蜜多心経"')
        assert counts() == [1, 0], ('Down swipe must clear all reservations and rewind', counts())
        swipe(-80); swipe(-80); swipe(80)
        assert counts() == [1, 0], 'At beginning, down swipe must only clear reservations'

        # A second finger outside the drum cancels the first finger's gesture.
        p = point(); outside = {'x':30,'y':p['y']}
        send('touchStart', [finger(p)])
        send('touchStart', [finger(p), finger(outside, 2)])
        send('touchMove', [finger({'x':p['x'],'y':p['y']-70}), finger(outside, 2)])
        send('touchEnd', [])
        time.sleep(.1)
        assert counts() == [1, 0], 'Multi-touch must not create an operation'
        assert 'pinch-zoom' in read('getComputedStyle(document.querySelector("#stage")).touchAction')
        tap()
        assert counts() == [2, 1], 'Tap after multi-touch must work'

        # Releasing a finger after restart/source switch must not turn the new state.
        p = point(); send('touchStart', [finger(p)])
        send('touchMove', [finger({'x':p['x'],'y':p['y']-60})])
        read('document.querySelector("#restartBtn").click()')
        send('touchEnd', []); time.sleep(.1)
        assert counts() == [0, 0]
        tap(); assert counts() == [1, 0]
        p = point(); send('touchStart', [finger(p)])
        send('touchMove', [finger({'x':p['x'],'y':p['y']-60})])
        read('document.querySelector("#sutraSelect").value="enmei";document.querySelector("#sutraSelect").dispatchEvent(new Event("change"))')
        wait('document.querySelector("#stage").getAttribute("aria-disabled") === "false"')
        send('touchEnd', []); time.sleep(.1)
        assert counts() == [0, 0]
        tap(); wait('testAudio.currentTime > .1')
        assert counts() == [1, 0]

        # The full-text panel keeps its ordinary native touch scroll.
        read('document.querySelector("#sutraSelect").value="hannya";document.querySelector("#sutraSelect").dispatchEvent(new Event("change"))')
        wait('document.querySelector("#stage").getAttribute("aria-disabled") === "false"')
        read('document.querySelector("#textBlock").scrollTop=0')
        start = point('#textBlock'); start['y'] += 45
        swipe(-90, origin=start)
        wait('document.querySelector("#textBlock").scrollTop > 0')
        assert counts() == [0, 0] and read('scrollY') == 0

        # Native pinch zoom remains available even when both fingers start on the drum.
        p = point()
        def pinch_points(distance):
            return [finger({'x':p['x'], 'y':p['y']-distance}),
                    finger({'x':p['x'], 'y':p['y']+distance}, 2)]
        send('touchStart', pinch_points(20))
        for distance in range(25, 101, 5):
            send('touchMove', pinch_points(distance))
            time.sleep(.02)
        send('touchEnd', [])
        wait('visualViewport.scale > 1.1')
        assert counts() == [0, 0], 'Pinch zoom must not turn the drum'
        assert not errors, errors
        browser.close()
    print('Real touch: startup tap, upward/long swipe, immediate downward rewind, no duplicate click PASS')
    print('Short/horizontal/canceled/multi-touch/reset/source switch, next tap, native text scroll and pinch zoom PASS')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8743/')
    check(parser.parse_args().url)
