"""Learner/admin UX checks against ASGI and an isolated, disposable bank."""

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from exam_trainer import bank, db
from exam_trainer.app import app
from exam_trainer.config import settings


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


with tempfile.TemporaryDirectory() as folder:
    settings.data_dir = Path(folder)
    settings.cache_dir = Path(folder) / 'cache'
    settings.admin_token = 'isolated-browser-token'
    settings.secure_cookies = False
    settings.searxng_url = 'http://unused.test'
    db.reset_for_tests(Path(folder))
    exam = bank.create_exam('学習と管理の表示を確認するための検定', 'ui-check')
    bank.set_syllabus(exam, [
        {'path': '1', 'title': '長い名前の学習範囲と基礎知識', 'keywords': '基本・用語'},
        {'path': '1.1', 'title': '基本問題'},
        {'path': '1.1.1.1.1', 'title': '階層の深い範囲'},
        {'path': '2', 'title': '問題を準備している範囲'},
    ])
    first = bank.add_question(exam, '1.1', '学習用の問題です。正しい選択肢を選んでください。',
                              ['正しい説明', '異なる説明', '別の説明'], 0,
                              explanation='正解の理由を確認します。' * 8, status='verified')
    second = bank.add_question(exam, '1.1.1.1.1', '次の学習用問題です。正しい説明はどれですか。',
                               ['正しい説明', '異なる説明', '別の説明'], 0, status='verified')
    empty_exam = bank.create_exam('準備中の検定', 'empty-ui-check')
    client = TestClient(app)
    failures = set()
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        errors = []
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(str(error))))

        def respond(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'exam.test':
                route.abort()
                return
            target = url.path + ('?' + url.query if url.query else '')
            requests.append((req.method, url.path))
            if url.path.endswith('/answer'):
                assert page.locator('#card').get_attribute('aria-busy') == 'true'
                assert page.locator('.choice').first.is_disabled()
                assert page.locator('#unsureBtn').is_disabled()
                page.locator('.choice').first.evaluate('(button) => button.click()')
            if url.path.endswith('/next'):
                assert page.locator('#nextBtn').is_disabled()
                page.locator('#nextBtn').evaluate('(button) => button.click()')
            if url.path in failures:
                failures.remove(url.path)
                route.fulfill(status=503, content_type='application/json',
                              body=json.dumps({'detail': '確認用の通信エラー'}))
                return
            headers = {'Content-Type': req.headers.get('content-type', '')}
            if 'cookie' in req.headers:
                headers['cookie'] = req.headers['cookie']
            res = client.request(req.method, target, content=req.post_data,
                                 headers=headers, follow_redirects=False)
            route.fulfill(status=res.status_code, headers=dict(res.headers), body=res.content)

        context.route('**/*', respond)
        page = context.new_page()
        for width in (1280, 768, 414, 375, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            for path in (f'/study?exam_id={exam}', f'/weakness?exam_id={exam}',
                         f'/study?exam_id={empty_exam}', '/admin/login?next=/admin/bank'):
                page.goto('http://exam.test' + path)
                no_overflow(page)
                name = urlsplit(path).path.strip('/').replace('/', '-')
                if path == f'/study?exam_id={empty_exam}':
                    name += '-empty'
                page.screenshot(path=f'/tmp/subpage-{name}-{width}.png', full_page=True)

        # Login errors retain the form and allow another attempt, including network failure.
        page.locator('#adminToken').fill('wrong')
        page.locator('#adminToken').press('Enter')
        page.wait_for_function('!document.getElementById("loginButton").disabled')
        assert page.locator('#loginStatus').inner_text()
        failures.add('/api/admin/session')
        page.locator('#adminToken').fill(settings.admin_token)
        page.locator('#loginButton').click()
        page.wait_for_function('!document.getElementById("loginButton").disabled')
        assert '確認用' in page.locator('#loginStatus').inner_text()
        # Route abort exercises fetch failure rather than just an HTTP error.
        page.route('**/api/admin/session', lambda route: route.abort())
        page.locator('#loginButton').click()
        page.wait_for_function('!document.getElementById("loginButton").disabled')
        assert '接続できません' in page.locator('#loginStatus').inner_text()
        page.unroute('**/api/admin/session')
        page.locator('#loginButton').click()
        page.wait_for_url('**/admin/bank')
        page.locator('#bankPage').wait_for(state='visible')

        for width in (1280, 768, 414, 375, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            page.goto(f'http://exam.test/admin/bank?exam_id={exam}')
            no_overflow(page)
            assert page.locator('.answer-label').count() == 2
            assert page.locator('.bank-tabs [aria-current]').count() == 1
            for trigger, dialog, cancel in (
                    ('materialBtn', 'materialModal', 'matCancel'),
                    ('generateBtn', 'generateModal', 'genCancel'),
                    ('addBtn', 'addModal', 'addCancel')):
                page.locator('#' + trigger).click()
                assert page.locator('#' + dialog).is_visible()
                no_overflow(page)
                assert page.evaluate(f'document.getElementById("{dialog}").contains(document.activeElement)')
                # Both edges of the dialog retain keyboard focus.
                for _ in range(18):
                    page.keyboard.press('Tab')
                    assert page.evaluate(f'document.getElementById("{dialog}").contains(document.activeElement) || document.activeElement === document.body'), f'{dialog}: focus escaped to a page control'
                page.keyboard.press('Tab')
                assert page.evaluate(f'document.getElementById("{dialog}").contains(document.activeElement) || document.activeElement === document.body')
                page.keyboard.press('Escape')
                assert page.locator('#' + dialog).is_hidden()
                assert page.evaluate('document.activeElement.id') == trigger
                page.locator('#' + trigger).click()
                page.locator('#' + cancel).click()
                assert page.evaluate('document.activeElement.id') == trigger
            page.evaluate('window.scrollTo(0, 0); document.activeElement.blur()')
            page.screenshot(path=f'/tmp/subpage-bank-{width}.png', full_page=True)
            page.goto(f'http://exam.test/admin/settings?exam_id={exam}')
            no_overflow(page)
            page.locator('a[href="#syllabusSection"]').click()
            assert page.locator('#outline').is_visible()
            page.locator('.input-guide summary').press('Enter')
            assert page.locator('.input-guide').get_attribute('open') is not None
            page.evaluate('window.scrollTo(0, 0); document.activeElement.blur()')
            page.screenshot(path=f'/tmp/subpage-settings-{width}.png', full_page=True)

        # Settings error remains visible and saving recovers without losing input.
        failures.add(f'/api/exams/{exam}/syllabus')
        outline = page.locator('#outline').input_value()
        page.locator('#saveSyllabus').click()
        page.wait_for_function('!document.getElementById("saveSyllabus").disabled')
        assert '確認用' in page.locator('#syllabusStatus').inner_text()
        assert page.locator('#outline').input_value() == outline
        page.locator('#saveSyllabus').click()
        page.wait_for_function('!document.getElementById("saveSyllabus").disabled')
        assert '4項目' in page.locator('#syllabusStatus').inner_text()
        page.locator('#addExam').click()
        assert '入力してください' in page.locator('#examStatus').inner_text()

        # A failed answer does not create history; one accepted choice writes one review.
        context.clear_cookies()
        client.cookies.clear()
        page.goto(f'http://exam.test/study?exam_id={exam}')
        assert int(page.locator('#card').get_attribute('data-question-id')) == first
        page.locator('#unsureBtn').click()
        assert page.locator('#unsureBtn').get_attribute('aria-pressed') == 'true'
        failures.add(f'/api/questions/{first}/answer')
        page.locator('#unsureBtn').press('A')
        page.wait_for_function('document.getElementById("card").getAttribute("aria-busy") === "false"')
        assert '確認用' in page.locator('#studyStatus').inner_text()
        assert not bank.recent_reviews(exam)
        assert page.locator('.choice').first.is_enabled()
        page.locator('#unsureBtn').press('A')
        page.locator('#nextBtn').wait_for(state='visible')
        assert len(bank.recent_reviews(exam)) == 1
        assert requests.count(('POST', f'/api/questions/{first}/answer')) == 2
        assert page.locator('.choice-mark').inner_text() == '正解'
        assert page.locator('#unsureRow').is_hidden()
        no_overflow(page)
        page.evaluate('window.scrollTo(0, 0); document.activeElement.blur()')
        page.screenshot(path='/tmp/subpage-study-result-320.png', full_page=True)
        failures.add(f'/api/exams/{exam}/next')
        page.locator('#nextBtn').press('Enter')
        page.wait_for_function('!document.getElementById("nextBtn").disabled')
        assert '再試行' in page.locator('#studyStatus').inner_text()
        assert int(page.locator('#card').get_attribute('data-question-id')) == first
        page.locator('#nextBtn').press('Enter')
        page.wait_for_function(f'document.getElementById("card").dataset.questionId === "{second}"')
        assert page.evaluate('document.activeElement.id') == 'stem'
        assert page.locator('#unsureBtn').get_attribute('aria-pressed') == 'false'
        page.keyboard.press('B')
        page.locator('#nextBtn').wait_for(state='visible')
        assert page.locator('#verdict').inner_text() == '不正解'
        assert page.locator('.choice-mark').count() == 2
        assert len(bank.recent_reviews(exam)) == 2
        page.goto(f'http://exam.test/weakness?exam_id={exam}')
        assert page.locator('.meter[role="meter"]').count() == 3
        assert page.locator('.scope-unavailable').inner_text() == '問題準備中'
        assert page.locator('.recent-row').count() == 2
        no_overflow(page)
        page.evaluate('window.scrollTo(0, 0); document.activeElement.blur()')
        page.screenshot(path='/tmp/subpage-weakness-answered-320.png', full_page=True)
        # Filter switch uses native keys, never submitting a study answer.
        page.goto(f'http://exam.test/study?exam_id={exam}')
        if page.locator('#nodeFilter').count():
            page.locator('#nodeFilter').focus()
            page.keyboard.press('A')
            assert len(bank.recent_reviews(exam)) == 2
        assert not errors, errors
        browser.close()
    db.close()
print('PASS subpages: 5 widths; native dialogs/focus; login and save retries; answer history; next retry; weakness links; no overflow or JS errors')
