"""Verify all five courses and archaeology learning/weakness with a temp bank."""

import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from exam_trainer import bank, db, learning_catalog, products
from exam_trainer.app import app, ADMIN_COOKIE
from exam_trainer.config import settings

with tempfile.TemporaryDirectory() as folder:
    settings.data_dir = Path(folder)
    settings.admin_token = 'catalog-browser-token'
    db.reset_for_tests(Path(folder))
    for key, name in products.EXAMS.items():
        eid = bank.create_exam(name, key)
        bank.set_syllabus(eid, [{'path': '1', 'title': '既存範囲'}])
        bank.add_question(eid, '1', name + 'の既存問題', ['正解', '誤答'], 0, status='verified')
    created = learning_catalog.import_missing()
    assert len(created) == 1 and created[0]['key'] == 'kouko'
    eid = created[0]['exam_id']
    client = TestClient(app)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        errors = []
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))

        def respond(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'exam.test':
                route.abort()
                return
            target = url.path + ('?' + url.query if url.query else '')
            res = client.request(req.method, target, content=req.post_data,
                                 headers={'Content-Type': req.headers.get('content-type', '')})
            route.fulfill(status=res.status_code, headers=dict(res.headers), body=res.content)

        context.route('**/*', respond)
        page = context.new_page()
        for width in (320, 375, 414, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            for path in ('/study', '/weakness'):
                page.goto('http://exam.test' + path)
                assert page.locator('#examSwitch option').count() == 5
                assert page.locator('#examSwitch option').all_text_contents() == list(learning_catalog.EXAMS.values())
                # Native picker keyboard navigation selects archaeology from the existing exam.
                page.locator('#examSwitch').focus()
                page.keyboard.press('Home')
                page.keyboard.press('Enter')
                page.wait_for_url(f'**{path}?exam_id={eid}')
                page.wait_for_function(f'document.querySelector("#examSwitch").value === "{eid}"')
                assert '未校閲の教材' in page.locator('#main-content').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.goto(f'http://exam.test/study?exam_id={eid}&node=2')
            qid = int(page.locator('#card').get_attribute('data-question-id'))
            q = bank.get_question(qid)
            assert q['node_path'] == '2'
            page.locator('.choice').nth(q['answer']).click()
            page.locator('#nextBtn').wait_for(state='visible')
            assert page.locator('#verdict').inner_text() == '正解'
            page.locator(f'.nav-links a[href="/weakness?exam_id={eid}"]').click()
            assert page.locator('.recent-row').count() > 0
            assert page.locator('#examSwitch').input_value() == str(eid)
            assert page.locator('.progress-row a[href*="node=2"]').count() == 1
            page.locator('.progress-row a[href*="node=2"]').click()
            page.locator('#study').wait_for(state='visible')
            assert page.locator('#study').get_attribute('data-node') == '2'
        client.cookies.set(ADMIN_COOKIE, settings.admin_token)
        for width in (320, 375, 414, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(f'http://exam.test/admin/bank?exam_id={eid}')
            assert page.locator('.q-row').count() == 50
            page.locator('.q-row details summary').first.press('Enter')
            assert '未校閲' in page.locator('.q-row details .request-status').first.inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        browser.close()
    db.close()
print('PASS both pickers show 5 courses; native keyboard switch; archaeology answer/weakness/scope links; bank provenance; 5 widths; no overflow or JS errors')
