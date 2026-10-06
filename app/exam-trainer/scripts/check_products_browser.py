"""Anonymous desktop/mobile funnel checks with an isolated bank and ASGI."""

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from exam_trainer import bank, db, products
from exam_trainer.app import app
from exam_trainer.config import settings


with tempfile.TemporaryDirectory() as folder:
    settings.data_dir = Path(folder)
    db.reset_for_tests(Path(folder))
    for key, name in products.EXAMS.items():
        eid = bank.create_exam(name, key)
        bank.set_syllabus(eid, [{'path':'1','title':'学習範囲'}])
        bank.add_question(eid, '1', name+'の学習用問題', ['正解','誤答A','誤答B','誤答C'], 0, status='verified')
    client = TestClient(app)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width':1280,'height':900})
        errors = []
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))
        def respond(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'exam.test':
                route.abort()
                return
            target = url.path + ('?' + url.query if url.query else '')
            if url.path.endswith('/trial/answer'):
                assert page.locator('#trial').get_attribute('aria-busy') == 'true'
                assert page.locator('#answer-status').is_visible()
            res = client.request(req.method, target, content=req.post_data,
                                 headers={'Content-Type':req.headers.get('content-type','')})
            route.fulfill(status=res.status_code, headers=dict(res.headers), body=res.content)
        context.route('**/*', respond)
        page = context.new_page()
        for width in (1280,768,414,375,320):
            page.set_viewport_size({'width':width,'height':900})
            page.goto('http://exam.test/')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'learning nav overflow at {width}'
            assert page.locator('.course-card').count() == 7
            page.keyboard.press('Tab')
            assert page.locator('.skip-link').evaluate('(node) => node === document.activeElement')
            page.keyboard.press('Enter')
            assert page.evaluate('document.activeElement.id') == 'main-content'
            page.locator('.nav-links a[href="/study"]').click()
            assert page.locator('#study').count() == 1
            page.locator('#examSwitch').select_option('3')
            page.wait_for_url('**/study?exam_id=3')
            assert page.locator('#study').get_attribute('data-exam-id') == '3'
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.locator('.nav-links a[href="/products"]').click()
            assert page.locator('.artifact').count() == 7
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
            page.screenshot(path=f'/tmp/product-catalog-{width}.png', full_page=True)
            for key in products.EXAMS:
                base = f'/products/{key}'
                product = products.load_product(key)
                page.goto('http://exam.test/products')
                page.locator(f'a[href="{base}"]').click()
                assert product['title'] in page.locator('h1').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.locator(f'.product-nav a[href="{base}/materials"]').click()
                assert page.locator('.artifact').count() == 7
                assert page.locator('.pdf-card').count() == 2
                assert page.locator('.production-materials').get_attribute('open') is None
                assert page.locator('.production-row').first.is_hidden()
                page.locator('.production-materials summary').press('Enter')
                assert page.locator('.production-row').first.is_visible()
                page.locator('.production-materials summary').press('Enter')
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
                page.screenshot(path=f'/tmp/product-{key}-materials-{width}.png', full_page=True)
                with page.expect_download() as pending:
                    page.locator(f'a[href="{base}/files/review-pdf?download=true"]').click()
                download = pending.value
                assert Path(download.path()).read_bytes() == (products.ARTIFACT_DIR / key / f'{key}-review.pdf').read_bytes()
                page.locator(f'.product-nav a[href="{base}/trial"]').click()
                assert json.loads(page.locator('#trial-data').text_content())[0]['stem'] == product['questions'][0]['stem']
                by_id = {q['id']:q for q in product['questions']}
                for qid in product['free_ids']:
                    q = by_id[qid]
                    page.locator('#choices button').nth(q['answer']).click()
                    page.locator('#next').wait_for(state='visible')
                    assert page.locator('#trial').get_attribute('aria-busy') == 'false'
                    assert page.locator('#explanation').inner_text() == q['explanation']
                    page.locator('#next').click()
                assert page.locator('#score').inner_text() == '10 / 10問正解'
                with page.expect_download() as pending:
                    page.locator('[data-result-pdf]').click()
                assert Path(pending.value.path()).read_bytes() == (products.ARTIFACT_DIR / key / f'{key}-review.pdf').read_bytes()
                page.evaluate("window.scrollTo(0, 0); document.activeElement.blur()")
                page.screenshot(path=f'/tmp/product-{key}-result-{width}.png', full_page=True)
                page.locator(f'.product-nav a[href="{base}/sample"]').click()
                assert page.locator('.sample-question').count() == 10
                page.locator('.sample-question summary').first.press('Enter')
                assert page.locator('.sample-question details').first.get_attribute('open') is not None
        assert not errors, errors
        browser.close()
    db.close()
print('PASS home catalog; study/exam switch; 7 products; PDF2 + production5 keyboard disclosure; trial/result PDF download; 320/375/414/768/1280; no overflow; no JS errors')
