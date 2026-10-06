"""Offline browser checks: use a temporary release manifest and ASGI transport.

Run with the existing project Python; no live service, database or account is
modified. Screenshots go to /tmp for inspection.
"""

import json, shutil, sys, tempfile
from pathlib import Path
from urllib.parse import urlsplit
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from exam_trainer import db, kouko
from exam_trainer.app import app
from exam_trainer.config import settings

with tempfile.TemporaryDirectory() as folder:
    original = kouko.PRODUCT_DIR
    for name in ['kouko.json', 'kouko-release.json']:
        shutil.copyfile(original/name, Path(folder)/name)
    kouko.PRODUCT_DIR = Path(folder)
    db.reset_for_tests(Path(folder) / 'bank')
    settings.admin_token = 'browser-check-temporary-token'
    client = TestClient(app)
    product = kouko.load_product()
    samples = kouko.sample_questions(product)
    failures = [0]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def respond(route):
            request = route.request
            url = urlsplit(request.url)
            if url.hostname != 'exam.test':
                route.abort()
                return
            if url.path == '/kouko/trial/answer' and failures[0]:
                failures[0] -= 1
                route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '接続を確認できませんでした'}))
                return
            target = url.path + (f'?{url.query}' if url.query else '')
            response = client.request(request.method, target, content=request.post_data,
                                      headers={'Content-Type': request.headers.get('content-type', '')})
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
        context.route('**/*', respond)
        page.goto('http://exam.test/')
        page.locator('.course-detail[href="/kouko"]').click()
        assert page.url == 'http://exam.test/kouko'
        for width in [1280,390]:
            page.set_viewport_size({'width':width,'height':900})
            page.goto('http://exam.test/kouko')
            assert page.locator('h1').inner_text().startswith('遺物と遺構')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
            page.screenshot(path=f'/tmp/kouko-{width}.png', full_page=True)
            page.locator('.product-nav a[href="/kouko/materials"]').click()
            assert page.locator('.artifact').count() == 7
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
            page.screenshot(path=f'/tmp/kouko-materials-{width}.png', full_page=True)
        with page.expect_download() as pending:
            page.locator('a[href="/kouko/files/review-pdf?download=true"]').click()
        download = pending.value
        download.save_as('/tmp/kouko-downloaded-review.pdf')
        assert Path('/tmp/kouko-downloaded-review.pdf').read_bytes() == (ROOT / 'docs/kouko/kouko-review.pdf').read_bytes()
        page.locator('.production-materials summary').press('Enter')
        assert page.locator('.production-materials').get_attribute('open') is not None
        with page.expect_popup() as pending:
            page.locator('a[href="/kouko/files/sales-copy"]').click()
        popup = pending.value
        popup.wait_for_load_state()
        assert 'BOOTH商品説明の原稿' in popup.locator('body').inner_text()
        popup.close()
        page.goto('http://exam.test/kouko/trial')
        failures[0] = 1
        page.locator('#choices button').nth(0).click()
        page.locator('#trial-error').wait_for(state='visible')
        assert page.locator('#progress').inner_text().startswith('1 / 10')
        for q in samples:
            page.locator('#choices button').nth(q['answer']).click()
            page.locator('#next').wait_for(state='visible')
            assert page.locator('#trial-error').is_hidden()
            page.locator('#next').click()
        assert page.locator('#score').inner_text() == '10 / 10問正解'
        page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
        page.screenshot(path='/tmp/kouko-result.png', full_page=True)
        page.locator('#restart').click()
        for q in samples:
            page.locator('#choices button').nth((q['answer']+1)%4).click()
            page.locator('#next').wait_for(state='visible')
            page.locator('#next').click()
        assert page.locator('#score').inner_text() == '0 / 10問正解'
        assert '読み返したい分野' in page.locator('#review-topics').inner_text()
        page.goto('http://exam.test/kouko/sample')
        assert page.locator('.sample-question').count() == 10
        page.locator('.sample-question summary').first.press('Enter')
        assert page.locator('.sample-question details').first.get_attribute('open') is not None
        page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
        page.screenshot(path='/tmp/kouko-sample-page.png', full_page=True)
        assert not errors, errors
        context.unroute('**/*', respond)
        page.goto((ROOT / 'docs/kouko/kouko-review.html').as_uri())
        page.emulate_media(media='print')
        page.set_viewport_size({'width':794,'height':1123})
        page.locator('.page').nth(2).screenshot(path='/tmp/kouko-pdf-page.png')
        browser.close()
    db.close()
    print('PASS no login; nav to materials; PDF download; text popup; desktop/mobile; no overflow; 10 correct/10 incorrect; retry; restart; keyboard details; no JS errors')
