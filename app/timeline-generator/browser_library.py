"""Real IndexedDB and file roundtrip, without a server or AI calls."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
URL = 'http://localhost:8532'
RECORD = {'theme': 'テスト年表', 'period': '全期間', 'generated_at': '2026-10-11T00:00:00Z',
          'source_mode': 'wikipedia', 'notice': '保存テスト',
          'events': [{'year': 1971, 'date': '1971年', 'title': '<script>window.injected=true</script>',
                      'description': '端末保存の確認。', 'quote': 'raw quote',
                      'source': {'url': 'https://ja.wikipedia.org/wiki/テスト', 'title': 'テスト', 'context_heading': '原文見出し'}}],
          'trace': {'secret': 'not portable'}, 'api_key': 'never-export-this'}
with TemporaryDirectory() as directory, sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    errors, api_calls = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def serve(route):
        path = route.request.url.removeprefix(URL).split('?')[0]
        if path.startswith('/api/'):
            api_calls.append(path)
            route.fulfill(status=503, content_type='application/json', body='{"error":"offline"}')
            return
        name = {'/library': 'library.html'}.get(path, path.lstrip('/'))
        if name in {'library.html', 'local-library.js', 'app.js', 'styles.css', 'tokens.css', 'favicon.svg'}:
            mime = 'text/html' if name.endswith('.html') else 'text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'image/svg+xml'
            route.fulfill(content_type=mime, body=(ROOT / name).read_bytes())
        else:
            route.fulfill(status=404, body='')
    context.route('**/*', serve)
    page.goto(URL + '/library')
    page.wait_for_function('document.querySelector("#local-count").textContent.includes("0件")')
    assert page.locator('#local-empty').is_visible()
    assert page.locator('#local-export').is_disabled()
    page.goto(URL + '/library?from=manage')
    page.wait_for_function('document.querySelector("#local-count").textContent.includes("0件")')
    assert page.locator('.masthead-nav a[aria-current]').inner_text() == '端末の年表'
    assert page.locator('.wordmark').get_attribute('href') == '/manage'
    assert page.locator('.masthead-nav a[href="/manage/quality"]').count() == 1
    assert not api_calls, api_calls
    assert page.evaluate('(record) => TimelineLibrary.save([record])', RECORD) == 1
    assert page.evaluate('(record) => TimelineLibrary.save([record])', RECORD) == 0
    page.reload()
    page.wait_for_function('document.querySelector("#local-count").textContent.includes("1件")')
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.locator('#local-list details').evaluate('(element) => element.open = true')
        for zoom in [1, 2]:
            page.evaluate('(zoom) => document.documentElement.style.fontSize = `${zoom * 100}%`', zoom)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, zoom)
            if width in [320, 1280] and zoom == 1:
                page.screenshot(path=f'/tmp/timeline-library-{width}.png', full_page=True)
        page.evaluate('document.documentElement.style.fontSize = "100%"')
    assert page.locator('.event-title').inner_text().startswith('<script>')
    assert page.evaluate('window.injected') is None
    assert page.locator('.source-link').get_attribute('rel') == 'noopener noreferrer'
    with page.expect_download() as download:
        page.locator('#local-export').click()
    backup = Path(directory) / 'backup.json'
    download.value.save_as(backup)
    raw = backup.read_text()
    data = json.loads(raw)
    assert len(data['timelines']) == 1
    assert all(secret not in raw for secret in ['raw quote', 'trace', 'api_key', 'never-export-this', 'context_heading'])
    page.once('dialog', lambda dialog: dialog.accept())
    page.get_by_role('button', name='端末から削除').click()
    page.wait_for_function('document.querySelector("#local-count").textContent.includes("0件")')
    page.wait_for_function('!document.querySelector("#local-import").disabled')
    page.locator('#local-import').set_input_files(str(backup))
    page.wait_for_function('document.querySelector("#local-count").textContent.includes("1件")')
    page.wait_for_function('!document.querySelector("#local-import").disabled')
    page.locator('#local-import').set_input_files(str(backup))
    page.wait_for_function('document.querySelector("#local-status").textContent.startsWith("0件")')
    # A batch with a valid new record and an unsafe URL must write neither.
    valid = RECORD | {'theme': '保存されない新規年表'}
    invalid = RECORD | {'events': [RECORD['events'][0] | {'source': {'title': 'bad', 'url': 'javascript:alert(1)'}}]}
    bad = Path(directory) / 'bad.json'
    bad.write_text(json.dumps(data | {'timelines': [valid, invalid]}))
    page.wait_for_function('!document.querySelector("#local-import").disabled')
    page.locator('#local-import').set_input_files(str(bad))
    page.wait_for_function('!document.querySelector("#local-error").hidden')
    assert page.locator('#local-status').inner_text() == '', 'A failed import must not retain the previous success message'
    assert len(page.evaluate('TimelineLibrary.list()')) == 1
    for payload in ['not json', json.dumps(data | {'version': 99})]:
        bad.write_text(payload)
        page.wait_for_function('!document.querySelector("#local-import").disabled')
        page.locator('#local-import').set_input_files(str(bad))
        page.wait_for_function('!document.querySelector("#local-error").hidden')
    try:
        page.evaluate('(record) => TimelineLibrary.save(Array.from({length: 100}, (_, index) => ({...record, theme: `extra ${index}`})))', RECORD)
        raise AssertionError('capacity limit accepted')
    except Exception as exc:
        assert '100件' in str(exc)
    assert len(page.evaluate('TimelineLibrary.list()')) == 1
    try:
        page.evaluate('(record) => TimelineLibrary.save(Array.from({length: 20}, (_, index) => ({...record, theme: `large ${index}`, events: Array.from({length: 50}, () => ({...record.events[0], description: "文".repeat(4000)}))})))', RECORD)
        raise AssertionError('aggregate byte limit accepted')
    except Exception as exc:
        assert '8MiB' in str(exc)
    assert len(page.evaluate('TimelineLibrary.list()')) == 1
    assert not api_calls, api_calls
    assert not errors, errors
    # Browser storage denial leaves the file export usable.
    page.evaluate('Object.defineProperty(window, "indexedDB", {value: {open() {throw new Error("storage denied")}}})')
    try:
        page.evaluate('TimelineLibrary.list()')
        raise AssertionError('denied storage accepted')
    except Exception as exc:
        assert 'storage denied' in str(exc)
    with page.expect_download():
        page.evaluate('(record) => TimelineLibrary.download([record])', RECORD)
    browser.close()
print('PASS: IndexedDB persistence, file roundtrip, atomic invalid-import rejection, deduplication, capacity/storage failures, 5 widths/200%, no generation API calls')
