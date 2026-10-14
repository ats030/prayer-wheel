#!/usr/bin/env python3
"""Exercise real media playback and recovery in desktop/touch Chromium."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def check(base):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.route("**/v.js", lambda route: route.abort())
        context.add_init_script("""
          const originalPlay = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() {
            window.testAudio = this;
            return originalPlay.call(this);
          };
        """)
        page = context.new_page()
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(base)
        page.wait_for_selector('#stage[aria-disabled="false"]')
        assert page.locator("#currentLine").inner_text() == "ドラムを回すと、読経が始まります。"
        assert page.locator(".reel-face.is-selected").inner_text() == "心経を回す"
        page.locator('#stage').click()
        page.wait_for_function("window.testAudio && testAudio.currentTime > .4")
        trace = page.evaluate("""async () => {
          const samples = [];
          const started = performance.now();
          await new Promise(resolve => {
            const sample = () => {
              samples.push({time: testAudio.currentTime,
                angle: parseFloat(document.getElementById('dial').style.getPropertyValue('--drum-turn')),
                character: document.querySelector('.reel-face.is-selected').dataset.character});
              if (performance.now()-started < 1000) requestAnimationFrame(sample); else resolve();
            };
            requestAnimationFrame(sample);
          });
          return samples;
        }""")
        assert trace[-1]['angle'] > trace[0]['angle'], trace
        assert len({s['character'] for s in trace}) >= 2, trace
        page.locator('#pauseBtn').click()
        frozen = page.locator('#dial').evaluate("e => e.style.getPropertyValue('--drum-turn')")
        page.wait_for_timeout(250)
        assert page.locator('#dial').evaluate("e => e.style.getPropertyValue('--drum-turn')") == frozen
        page.emulate_media(reduced_motion='reduce')
        page.wait_for_function("document.getElementById('dial').dataset.moving === 'false'", timeout=500)
        page.wait_for_function("""() => {
          const position = parseFloat(document.getElementById('dial').style.getPropertyValue('--drum-turn')) / 7.5;
          return position === Math.round(position);
        }""", timeout=500)
        position = page.locator('#dial').evaluate("e => parseFloat(e.style.getPropertyValue('--drum-turn')) / 7.5")
        assert position == int(position)
        page.locator('#restartBtn').click()
        assert page.locator('.reel-face.is-selected').inner_text() == '心経を回す'
        page.emulate_media(reduced_motion='no-preference')
        page.locator("#stage").focus()
        page.keyboard.press("Space")
        assert page.locator("#pauseBtn").inner_text() == "一時停止"
        page.locator("#stage").click()
        page.wait_for_function("window.testAudio && testAudio.currentTime > 0.1")
        assert page.locator(".chunk.active").inner_text().strip() == "摩訶般若波羅蜜多心経"
        # Add five waiting sections without letting real playback finish first.
        page.evaluate("for(let i=0;i<5;i++)document.getElementById('stage').click()")
        assert page.locator("#queueCount").inner_text() == "5"
        assert page.locator("#counter").inner_text() == "6"
        assert page.locator(".reel-face.is-selected").get_attribute("data-section") == "0"
        page.evaluate("document.getElementById('stage').click()")
        assert page.locator("#counter").inner_text() == "6"
        assert page.locator("#currentLine").inner_text() == "摩訶般若波羅蜜多心経"
        page.locator("#backBtn").click()
        assert page.locator("#queueCount").inner_text() == "4"
        assert page.locator(".reel-face.is-selected").get_attribute("data-section") == "0"
        page.locator("#pauseBtn").click()
        assert page.locator('.reel-face.is-selected').get_attribute('data-section') == '0'
        before = page.evaluate("testAudio.currentTime")
        page.wait_for_timeout(250)
        assert abs(page.evaluate("testAudio.currentTime") - before) < .05
        page.locator("#rate").evaluate("e=>{e.value='1.25';e.dispatchEvent(new Event('input'))}")
        assert page.evaluate("testAudio.playbackRate") == 1.25
        page.locator("#pauseBtn").click()
        page.wait_for_function("testAudio.currentTime > " + str(before + .1))
        page.wait_for_function("document.getElementById('currentLine').textContent === '観自在菩薩'")
        assert page.evaluate("testAudio.playbackRate") == 1.25
        assert page.locator("#rounds").inner_text() == "0"
        page.locator("#restartBtn").click()
        assert page.locator("#counter").inner_text() == "0"
        assert page.locator("#queueCount").inner_text() == "0"
        assert page.locator(".chunk.active").count() == 0
        assert page.locator(".reel-face.is-selected").inner_text() == "心経を回す"
        # Actual wheel input and key controls.
        page.locator("#stage").hover()
        page.mouse.wheel(0, 120)
        page.wait_for_function("document.getElementById('counter').textContent === '1'")
        page.locator("#stage").focus()
        page.keyboard.press("ArrowDown")
        assert page.locator("#counter").inner_text() == "2"
        page.keyboard.press("ArrowUp")
        assert page.locator("#counter").inner_text() == "1"
        page.keyboard.press("Space")
        assert page.locator("#pauseBtn").inner_text() == "再開"
        assert page.locator("#stage").get_attribute("data-state") == "paused"
        page.wait_for_function("document.getElementById('dial').dataset.moving === 'false'")
        assert page.evaluate("""() => {
          const face = document.querySelector('.reel-face.is-selected').getBoundingClientRect();
          const line = document.querySelector('.reel-stop-line').getBoundingClientRect();
          const window = document.querySelector(".reel-window").getBoundingClientRect();
          return face.top >= window.top - 1 && face.bottom <= window.bottom + 1;
        }""")
        page.screenshot(path="/tmp/prayer-wheel-desktop.png", full_page=True)

        # A failed file remains on the same section, and a gesture can retry it.
        page.locator("#restartBtn").click()
        page.route("**/audio/synced/*/01.wav", lambda route: route.fulfill(status=404, body="missing"))
        page.locator("#stage").click()
        page.wait_for_selector("#retryBtn:visible")
        assert page.locator(".chunk.active").count() == 0
        assert page.locator("#rounds").inner_text() == "0"
        page.unroute("**/audio/synced/*/01.wav")
        page.locator("#retryBtn").click()
        page.wait_for_function("testAudio.currentTime > .1")
        assert page.locator("#counter").inner_text() == "1"
        assert page.locator("#retryBtn").is_hidden()
        assert not any(":50021" in url or ":50121" in url for url in requests)
        assert not errors, errors

        # Touch screen uses the same actual media element; check horizontal fit.
        mobile = browser.new_context(viewport={"width": 390, "height": 844},
                                     is_mobile=True, has_touch=True, device_scale_factor=1)
        mobile.route("**/v.js", lambda route: route.abort())
        mobile.add_init_script("""
          const originalPlay = HTMLMediaElement.prototype.play;
          HTMLMediaElement.prototype.play = function() { window.testAudio = this; return originalPlay.call(this); };
        """)
        touch = mobile.new_page()
        touch.on("pageerror", lambda error: errors.append(str(error)))
        touch.goto(base)
        touch.wait_for_selector('#stage[aria-disabled="false"]')
        touch.locator("#stage").tap()
        touch.wait_for_selector(".chunk.active")
        assert touch.locator("#counter").inner_text() == "1"
        assert touch.evaluate("document.documentElement.scrollWidth") <= 390
        touch.wait_for_function("testAudio.currentTime > .4")
        touch.screenshot(path="/tmp/prayer-wheel-mobile.png", full_page=True)
        touch.locator("#pauseBtn").tap()
        assert touch.locator("#pauseBtn").inner_text() == "再開"
        # A lower section in the text panel must actually become visible.
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#restartBtn").click()
        page.evaluate("""() => {
          for (let i=0;i<document.querySelectorAll('.chunk').length;i++) {
            document.getElementById('stage').click();
            // This isolated scroll assertion accelerates media progression.
            testAudio.dispatchEvent(new Event('playing'));
            testAudio.dispatchEvent(new Event('ended'));
          }
        }""")
        assert page.locator("#textBlock").evaluate("e=>e.scrollTop") > 0
        assert page.evaluate("""() => {
          const active = document.querySelector('.chunk.active').getBoundingClientRect();
          const panel = document.getElementById('textBlock').getBoundingClientRect();
          return active.top >= panel.top && active.bottom <= panel.bottom;
        }""")
        # A large target jump must not relabel the face still physically in view.
        assert page.evaluate("""async () => {
          const dial = document.getElementById('dial');
          const aligned = () => {
            const center = Math.round(parseFloat(dial.style.getPropertyValue('--drum-turn')) / 7.5);
            const slot = ((center % 48) + 48) % 48;
            return dial.children[slot].dataset.sequence === String(center);
          };
          if (!aligned()) return false;
          for (let i=0;i<28;i++) document.getElementById('backBtn').click();
          if (!aligned()) return false;
          await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          return aligned();
        }""")
        touch.locator("#stage").tap()
        assert touch.locator("#queueCount").inner_text() == "1"
        touch.locator("#backBtn").tap()
        assert touch.locator("#queueCount").inner_text() == "0"
        assert touch.locator("#pauseBtn").inner_text() == "再開"
        assert not errors, errors

        failed = context.new_page()
        failed.route("**/data/sutra-sections.json", lambda route: route.fulfill(status=503, body="unavailable"))
        failed.goto(base)
        failed.wait_for_selector("#reloadBtn:visible")
        assert failed.locator("#stage").get_attribute("aria-disabled") == "true"
        assert failed.locator("#stage").get_attribute("data-state") == "error"
        assert failed.locator("#stage").evaluate("e=>getComputedStyle(e).cursor") == "default"
        failed.unroute("**/data/sutra-sections.json")
        failed.locator("#reloadBtn").click()
        failed.wait_for_selector('#stage[aria-disabled="false"]')

        # Stale cue text or an audio URL from another version must fail closed.
        for mismatch in ('text', 'audio'):
            cues = json.loads((ROOT / 'dist/data/character-timing.json').read_text(encoding='utf-8'))
            if mismatch == 'text':
                cues['sutraSha256'] = '0' * 64
            else:
                cues['sections'][0]['file'] = cues['sections'][1]['file']
            invalid = context.new_page()
            invalid.route('**/data/character-timing.json', lambda route, request, body=json.dumps(cues):
                          route.fulfill(status=200, content_type='application/json', body=body))
            invalid.goto(base)
            invalid.wait_for_selector('#reloadBtn:visible')
            assert invalid.locator('#stage').get_attribute('aria-disabled') == 'true'
            invalid.close()

        # Exercise every section's layout at the four component-design widths.
        # Media events are accelerated here only; playback above uses real WAVs.
        layout = context.new_page()
        layout.emulate_media(reduced_motion="reduce")
        for width in (320, 375, 414, 768, 1280):
            layout.set_viewport_size({"width": width, "height": 900})
            layout.goto(base)
            layout.wait_for_selector('#stage[aria-disabled="false"]')
            result = layout.evaluate("""() => {
              const failures = [];
              const layoutFailures = [];
              for (const box of document.querySelectorAll('.grid,.panel,.stage,.drum-heading,.drum-meter,.drum-selection,.controls,.btn')) {
                const rect = box.getBoundingClientRect();
                if (rect.left < -1 || rect.right > innerWidth + 1) layoutFailures.push(box.className);
              }
              const count = document.querySelectorAll('.chunk').length;
              for (let i=0;i<count;i++) {
                document.getElementById('stage').click();
                testAudio.dispatchEvent(new Event('playing'));
                const face = document.querySelector('.reel-face.is-selected');
                if (face.dataset.section !== String(i) || face.scrollHeight > face.clientHeight
                    || face.scrollWidth > face.clientWidth) failures.push(i);
                const windowRect = document.querySelector('.reel-window').getBoundingClientRect();
                const previous = [...document.querySelectorAll('.reel-face')].find(row => Number(row.dataset.sequence) === Number(face.dataset.sequence) - 1);
                if (i > 0 && (!previous || previous.textContent !== '')) failures.push('spacer-'+i);
                for (const rule of document.querySelectorAll('.reel-face,.reel-stop-line')) {
                  const css = getComputedStyle(rule);
                  if (css.borderTopWidth !== '0px' || css.borderBottomWidth !== '0px') failures.push('rule-'+i);
                }
                for (const row of document.querySelectorAll('.reel-face')) {
                  if (Math.abs(Number(row.dataset.sequence) - Number(face.dataset.sequence)) > 4 || !row.textContent) continue;
                  const range = document.createRange();
                  range.selectNodeContents(row);
                  const text = range.getBoundingClientRect();
                  if (text.left < windowRect.left - 1 || text.right > windowRect.right + 1
                      || text.top < windowRect.top - 1 || text.bottom > windowRect.bottom + 1) failures.push('text-'+i);
                }
                testAudio.dispatchEvent(new Event('ended'));
              }
              const completedState = document.getElementById('stage').dataset.state;
              document.getElementById('stage').click();
              testAudio.dispatchEvent(new Event('playing'));
              const wrapped = document.querySelector('.reel-face.is-selected');
              const wrapSpacer = [...document.querySelectorAll('.reel-face')].find(row => Number(row.dataset.sequence) === Number(wrapped.dataset.sequence) - 1);
              if (!wrapSpacer || wrapSpacer.textContent !== '') failures.push('wrap-spacer');
              testAudio.dispatchEvent(new Event('ended'));
              return {count, failures, layoutFailures, completedState, idleState: document.getElementById('stage').dataset.state,
                sequence: wrapped.dataset.section,
                width: document.documentElement.scrollWidth,
                transition: getComputedStyle(document.getElementById('dial')).transitionDuration};
            }""")
            assert not result["failures"], (width, result)
            assert not result["layoutFailures"], (width, result)
            assert result["completedState"] == "success" and result["idleState"] == "ready", result
            assert result["width"] <= width, (width, result)
            assert result["sequence"] == str(result["count"])
            assert result["transition"] == "0s"
            layout.wait_for_function("document.getElementById('dial').dataset.moving === 'false'")
            assert layout.locator('#dial').evaluate("e => parseFloat(e.style.getPropertyValue('--drum-turn'))") == layout.locator('.reel-face.is-selected').evaluate("e => Number(e.dataset.sequence) * 7.5")
            layout.evaluate("""() => {
              document.getElementById('stage').click();
              document.getElementById('pauseBtn').click();
              document.getElementById('backBtn').click();
            }""")
            assert layout.locator("#stage").get_attribute("data-state") == "paused"
            assert layout.locator(".reel-face.is-selected").get_attribute("data-section") == str(result["count"])
            assert layout.locator("#pauseBtn").inner_text() == "再開"
            layout.locator("#restartBtn").click()
            assert layout.locator(".reel-face.is-selected").inner_text() == "心経を回す"
        browser.close()
    print("Desktop and touch Chromium: real WAV playback, queue, reverse, pause/resume, rate, reset, recovery PASS")
    print("Screenshots: /tmp/prayer-wheel-desktop.png /tmp/prayer-wheel-mobile.png")
    print("Drum states/selection/cancellation/wrap/reset; center and neighbor text at 320/375/414/768/1280px; reduced motion PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8731")
    check(parser.parse_args().url)
