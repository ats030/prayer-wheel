#!/usr/bin/env python3
"""Exercise real media playback and recovery in desktop/touch Chromium."""
import argparse
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
        assert page.locator("#currentLine").inner_text() == "輪を回すと、読経が始まります。"
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
        page.evaluate("document.getElementById('stage').click()")
        assert page.locator("#counter").inner_text() == "6"
        assert page.locator("#currentLine").inner_text() == "摩訶般若波羅蜜多心経"
        page.locator("#backBtn").click()
        assert page.locator("#queueCount").inner_text() == "4"
        page.locator("#pauseBtn").click()
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
        page.screenshot(path="/tmp/prayer-wheel-desktop.png", full_page=True)

        # A failed file remains on the same section, and a gesture can retry it.
        page.locator("#restartBtn").click()
        page.route("**/audio/01.wav", lambda route: route.fulfill(status=404, body="missing"))
        page.locator("#stage").click()
        page.wait_for_selector("#retryBtn:visible")
        assert page.locator(".chunk.active").count() == 0
        assert page.locator("#rounds").inner_text() == "0"
        page.unroute("**/audio/01.wav")
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
        touch = mobile.new_page()
        touch.on("pageerror", lambda error: errors.append(str(error)))
        touch.goto(base)
        touch.wait_for_selector('#stage[aria-disabled="false"]')
        touch.locator("#stage").tap()
        touch.wait_for_selector(".chunk.active")
        assert touch.locator("#counter").inner_text() == "1"
        assert touch.evaluate("document.documentElement.scrollWidth") <= 390
        touch.screenshot(path="/tmp/prayer-wheel-mobile.png", full_page=True)
        touch.locator("#pauseBtn").tap()
        assert touch.locator("#pauseBtn").inner_text() == "再開"
        # A lower section in the text panel must actually become visible.
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#restartBtn").click()
        page.evaluate("""() => {
          for (let i=0;i<20;i++) {
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
        touch.locator("#stage").tap()
        assert touch.locator("#queueCount").inner_text() == "1"
        touch.locator("#backBtn").tap()
        assert touch.locator("#queueCount").inner_text() == "0"
        assert touch.locator("#pauseBtn").inner_text() == "再開"
        assert not errors, errors

        failed = context.new_page()
        failed.route("**/data/sutra.json", lambda route: route.fulfill(status=503, body="unavailable"))
        failed.goto(base)
        failed.wait_for_selector("#reloadBtn:visible")
        assert failed.locator("#stage").get_attribute("aria-disabled") == "true"
        failed.unroute("**/data/sutra.json")
        failed.locator("#reloadBtn").click()
        failed.wait_for_selector('#stage[aria-disabled="false"]')
        browser.close()
    print("Desktop and touch Chromium: real WAV playback, queue, reverse, pause/resume, rate, reset, recovery PASS")
    print("Screenshots: /tmp/prayer-wheel-desktop.png /tmp/prayer-wheel-mobile.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8731")
    check(parser.parse_args().url)
