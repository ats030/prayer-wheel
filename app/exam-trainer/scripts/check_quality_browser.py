"""Exercise admin diagnosis UI against an isolated bank, without model calls."""
import csv
import io
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from exam_trainer import db, quality
from exam_trainer.app import app, ADMIN_COOKIE
from exam_trainer.config import settings

with tempfile.TemporaryDirectory() as folder:
    settings.data_dir = Path(folder)
    settings.admin_token = 'quality-browser-token'
    db.reset_for_tests(Path(folder))
    quality.start_worker = lambda: None
    client = TestClient(app)
    assert client.get('/admin/quality', follow_redirects=False).status_code == 303
    client.cookies.set(ADMIN_COOKIE, settings.admin_token)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(accept_downloads=True)
        errors = []
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        fail_next = {'start': True}

        def respond(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname != 'exam.test':
                route.abort()
                return
            if url.path == '/api/quality/runs' and fail_next['start']:
                fail_next['start'] = False
                route.fulfill(status=503, content_type='application/json', body='{"detail":"接続エラー"}')
                return
            target = url.path + ('?' + url.query if url.query else '')
            res = client.request(req.method, target, content=req.post_data,
                                 headers={'Content-Type': req.headers.get('content-type', '')})
            route.fulfill(status=res.status_code, headers=dict(res.headers), body=res.content)

        context.route('**/*', respond)
        page.goto('http://exam.test/admin/quality')
        assert '診断はまだありません' in page.locator('#main-content').inner_text()
        page.locator('#useLlm').uncheck()
        page.locator('#startQuality').click()
        page.wait_for_function('document.querySelector("#qualityMessage").textContent.includes("接続エラー")')
        assert page.locator('#startQuality').is_enabled()
        page.locator('#startQuality').click()
        page.wait_for_url('**/admin/quality?run_id=*')
        run_id = int(page.locator('#qualityPage').get_attribute('data-run-id'))
        assert page.locator('#startQuality').is_disabled()
        quality.execute(run_id)
        page.locator('#qualityRefresh').click()
        page.locator('#reviewFile').wait_for()
        page.goto(f'http://exam.test/admin/quality?run_id={run_id}&sampled=true')
        for width in (320, 375, 414, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.locator('.quality-item').count() == 30
            first = page.locator('.quality-item > details > summary').first
            first.focus()
            page.keyboard.press('Enter')
            assert page.locator('.quality-item > details').first.get_attribute('open') is not None
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.keyboard.press('Enter')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=f'/tmp/exam-trainer-quality-{width}.png')
        with page.expect_download() as info:
            page.locator('a[href$="review.csv"]').click()
        saved = Path(folder) / 'review.csv'
        info.value.save_as(saved)
        records = list(csv.DictReader(io.StringIO(saved.read_text(encoding='utf-8-sig'))))
        assert len(records) == 30 and all(not row['human_verdict'] for row in records)
        records[0].update(human_verdict='unknown', reviewer='ブラウザ検証', notes='隔離データでの操作確認')
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=quality.CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)
        saved.write_text(out.getvalue(), encoding='utf-8-sig')
        page.locator('#reviewFile').set_input_files(saved)
        page.locator('#importQuality').click()
        page.wait_for_function('document.querySelector("#main-content").textContent.includes("確認記録 1件")')
        assert not errors, errors
        browser.close()
    db.close()
print('quality browser: empty/error/retry/progress, 5 widths, keyboard, CSV download/import passed')
