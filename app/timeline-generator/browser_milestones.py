"""Exercise the editor against real HTTP/storage in a disposable DB, without generation."""
import json
import tempfile
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright
from jobs import JobStore, QueueWorker
from timeline import parse_query
from server import Handler


def main():
    with tempfile.TemporaryDirectory() as directory:
        store = JobStore(directory + '/browser.sqlite3')
        job = store.submit(parse_query('昭和'))[0]
        store.claim()
        result = {'kind': 'result', 'theme': '昭和', 'period': '全期間', 'events': [
            {'year': 1972, 'date': '1972年', 'title': '沖縄返還', 'description': '沖縄が日本に返還された。',
             'source': {'url': 'https://example.org/history', 'title': '出典'}}],
            'review_notes': [], 'notice': 'ブラウザ検証用', 'elapsed_seconds': 1, 'stop_reason': 'sources_exhausted'}
        store.record(job['id'], result)
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        http.daemon_threads = True
        http.jobs = store
        http.worker = QueueWorker(store, lambda *args: None)  # Intentionally never start a worker.
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        root = f'http://127.0.0.1:{http.server_port}'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.route('**/v.js', lambda route: route.abort())
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(root + f"/timelines/{job['id']}")
                page.locator('#milestones-section').wait_for(state='visible')
                assert '重点的に調べる項目を指定' in page.locator('#milestone-link').inner_text()
                # A missing evaluation item becomes an editable request, never an
                # automatic save, model call, or change to the shared gold.
                page.locator('[data-missing="東京オリンピック"]').click()
                assert page.locator('#milestones-editor').evaluate('(element) => element.open')
                assert page.locator('[data-key="name"]').input_value() == '東京オリンピック'
                assert page.locator('[data-key="year"]').input_value() == '1964'
                assert store.get(job['id'])['requested_milestones'] == []
                assert not http.worker.wake.is_set()
                page.locator('[data-missing="東京オリンピック"]').click()
                assert page.locator('.milestone-row').count() == 1
                page.locator('#milestone-reload').click()
                page.locator('#milestones-editor summary').click()
                page.locator('#milestones-editor summary').click()
                page.locator('#milestone-import').click()
                assert page.locator('.milestone-row').count() > 0
                page.locator('#milestone-reload').click()
                assert page.locator('.milestone-row').count() == 0
                page.locator('#milestone-add').click()
                page.locator('[data-key="name"]').fill('沖縄返還')
                page.locator('[data-key="year"]').fill('1972')
                page.locator('[data-key="note"]').fill('<script>window.injected=true</script>')
                # Polling must not destroy in-progress input.
                page.wait_for_timeout(2200)
                assert page.locator('[data-key="name"]').input_value() == '沖縄返還'
                page.locator('#milestone-regenerate').click()
                assert '保存してから' in page.locator('#milestones-error').inner_text()
                assert store.get(job['id'])['state'] == 'complete'
                for width in [320, 375, 414, 768, 1280]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    for size in ['100%', '200%']:
                        page.evaluate('(size) => document.documentElement.style.fontSize = size', size)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, size)
                page.evaluate("document.documentElement.style.fontSize = '100%'")
                page.locator('#milestones-form button[type="submit"]').click()
                page.wait_for_function("document.getElementById('milestones-message').textContent.includes('保存しました')")
                saved = store.get(job['id'])
                assert saved['state'] == 'complete' and saved['result'] == result
                assert saved['requested_milestones'][0]['name'] == '沖縄返還'
                assert not http.worker.wake.is_set()
                assert '一致する項目あり' in page.locator('#milestone-report').inner_text()
                assert '1 / 1一致' in page.locator('#milestone-link').inner_text()
                assert not page.evaluate('Boolean(window.injected)')
                # Another tab updates the stored revision; preserve the local draft.
                page.locator('[data-key="name"]').fill('東京オリンピック')
                store.save_milestones(job['id'], [], saved['milestones_revision'])
                page.wait_for_function("document.getElementById('milestones-message').textContent.includes('別の画面')")
                page.locator('#milestones-form button[type="submit"]').click()
                page.wait_for_function("document.getElementById('milestones-error').textContent.includes('別の画面')")
                assert page.locator('[data-key="name"]').input_value() == '東京オリンピック'
                page.locator('#milestone-reload').click()
                assert page.locator('.milestone-row').count() == 0
                # Twelve item bound and deletion; optional fields work with name alone.
                for index in range(12):
                    page.locator('#milestone-add').click()
                    page.locator('[data-key="name"]').nth(index).fill(f'出来事 {index}')
                assert page.locator('#milestone-add').is_disabled()
                page.locator('.milestone-row button').last.click()
                assert page.locator('#milestone-add').is_enabled()
                page.locator('#milestone-reload').click()
                page.locator('#milestone-add').click()
                page.locator('[data-key="name"]').fill('沖縄返還')
                page.locator('#milestones-form button[type="submit"]').click()
                page.wait_for_function("document.getElementById('milestones-message').textContent.includes('保存しました')")
                page.locator('#milestone-regenerate').click()
                page.wait_for_function("document.getElementById('job-status').textContent === '待機中'")
                assert page.locator('#milestones-fields').evaluate('(element) => element.disabled')
                assert page.locator('[data-key="name"]').is_disabled()
                assert store.get(job['id'])['requested_milestones'][0]['name'] == '沖縄返還'
                assert store.get(job['id'])['result'] == result
                assert page.locator('[data-missing]').first.is_disabled()
                assert not errors, errors
                browser.close()
            print('milestone browser: 5 widths, 200% text, edit/save/remove/import, unsaved guard, revision conflict, XSS, regeneration snapshot passed')
        finally:
            http.shutdown(); http.server_close(); thread.join(); store.close()


if __name__ == '__main__':
    main()
