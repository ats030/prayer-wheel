"""Synthetic UI checks for queued/saved states; optional --live tests real generation."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

URL = os.environ.get("TIMELINE_TEST_URL", "http://100.94.207.13:8532")
RESULT = {"kind": "result", "theme": "テスト用の年表", "period": "1900年〜", "elapsed_seconds": 1.2, "notice": "ブラウザ検証専用の応答です。", "events": [{"year": 1971, "date": "1971年", "title": "テスト用の出来事", "description": '<script>window.injected=true</script> テスト本文。', "quote": "In 1971, a test event occurred.", "source": {"url": "https://example.org/history", "title": "Test history source", "context_heading": "1971年 <script>window.injected=true</script>"}}]}
BASE = {"id": 1, "query": "テストテーマ 1900年以降", "state": "queued", "message": "登録順に生成します。", "stage": None, "error": None, "has_result": False, "result": None, "generated_at": None}
RESULT['review_notes']=[{'date':'1683年','title':'テスト用の候補','reason':'伝説と史料に矛盾。<script>window.injected=true</script>','sources':[{'title':'補足資料','url':'https://example.org/other'},{'title':'無効なリンク','url':'javascript:window.injected=true'}]}]

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    job = BASE.copy()
    total = 1
    posted = []
    def respond(route):
        global job
        request = route.request
        path = request.url.split(URL)[-1]
        if request.method == "POST":
            posted.append(path)
            if path.endswith("/retry") or path.endswith("/regenerate"):
                job = job | {"state": "queued", "error": None, "message": "登録順に生成します。"}
            elif json.loads(request.post_data).get("query") == "エラー":
                route.fulfill(status=503, content_type="application/json", body=json.dumps({"error": "テスト用の接続エラー"}))
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(job))
        elif path.startswith("/api/jobs?"):
            listed = {key: value for key, value in job.items() if key != "result"}
            listed["event_count"] = len(job["result"]["events"]) if job.get("result") else None
            listed["stop_reason"] = job["result"].get("stop_reason") if job.get("result") else None
            listing = [listed]
            if "offset=50" in path:
                listing = listing if total > 50 else []
            elif total > 50:
                listing = [listing[0] | {"id": i + 1} for i in range(50)]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"jobs": listing if total else [], "total": total}))
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(job))
    context.route("**/api/jobs**", respond)
    # Synthetic document responses have no private-address metadata in Chromium.
    # Read working-tree assets to verify changes before deployment; live mode
    # removes all fixture routes and checks the deployed HTML and assets.
    asset_patterns = ["**/styles.css", "**/tokens.css", "**/app.js", "**/favicon.svg"]
    for pattern in asset_patterns:
        asset = pattern.split('/')[-1]
        mime = 'text/javascript' if asset.endswith('.js') else 'image/svg+xml' if asset.endswith('.svg') else 'text/css'
        context.route(pattern, lambda route, request, asset=asset, mime=mime: route.fulfill(content_type=mime, body=Path(__file__).with_name(asset).read_bytes()))
    fixture_pages = {'/': 'index.html', '/timelines': 'timelines.html', '/timelines/1': 'detail.html', '/changelog': 'changelog.html'}
    def serve_page(route):
        filename = fixture_pages.get(urlsplit(route.request.url).path)
        if filename and route.request.url.startswith(URL):
            route.fulfill(content_type='text/html; charset=utf-8', body=Path(__file__).with_name(filename).read_bytes())
        else:
            route.fallback()
    context.route('**/*', serve_page)
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({"width": width, "height": 900})
        for path in ["/", "/timelines", "/timelines/1", "/changelog"]:
            page.goto(URL + path, wait_until="domcontentloaded")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (path, width)
            for element in page.locator("button:visible, .quiet-link:visible").all():
                assert element.evaluate("e => e.getBoundingClientRect().height >= 44"), (path, width, "touch target")
            if width == 1280 and path in ['/timelines', '/timelines/1']:
                group = '.pagination' if path == '/timelines' else '.job-actions'
                assert page.locator(group).evaluate("e => {const a=e.getBoundingClientRect(), b=document.getElementById('page-heading').getBoundingClientRect(); return Math.abs((a.top+a.bottom)/2-(b.top+b.bottom)/2)<12;}"), (path, 'heading/actions alignment')
        page.screenshot(path=f"/tmp/timeline-generator-queue-{width}.png", full_page=True)
    page.goto(URL)
    page.locator("#submit").click()
    assert page.locator("#form-error").is_visible()
    page.locator("#query").fill(BASE["query"])
    page.locator("#query").press("Enter")
    page.locator("#receipt").wait_for()
    assert page.locator("#query").is_enabled()
    assert page.locator("#receipt-link").get_attribute("href") == "/timelines/1"
    page.locator("#query").fill("次のテーマ")
    page.locator("#submit").click()
    page.wait_for_function("!document.getElementById('submit').disabled")
    assert posted.count("/api/jobs") == 2
    assert page.locator("#how").get_attribute("open") is None
    page.locator("#receipt-link").click()
    page.locator("#job-status").wait_for()
    assert page.locator("#job-status").inner_text() == "待機中"
    assert page.locator('#result-meta').is_hidden() and page.locator('#generation-info').is_hidden()
    assert page.locator('.status-section #job-status').is_visible()
    job = job | {"state": "running", "stage": "verify", "message": "テスト用の照合中"}
    page.locator("#progress").wait_for()
    assert page.locator(".steps li.current").inner_text() == "根拠を照合"
    job = job | {"state": "complete", "has_result": True, "result": RESULT, "generated_at": "2026-10-02T09:00:00+00:00"}
    page.locator(".event").wait_for()
    assert not page.evaluate("Boolean(window.injected)")
    assert page.locator(".event p").first.inner_text().startswith("<script>")
    assert page.locator("#generation-info").get_attribute("open") is None
    assert page.locator('#result-meta').is_visible()
    assert page.locator('#generation-info').evaluate("e => {const meta=document.getElementById('result-meta').getBoundingClientRect(), state=document.getElementById('job-status').getBoundingClientRect(), info=e.getBoundingClientRect();return Math.abs((meta.top+meta.bottom)/2-(state.top+state.bottom)/2)<2 && Math.abs((info.top+info.bottom)/2-(state.top+state.bottom)/2)<2;}")
    assert page.locator("#generation-notice").is_hidden()
    assert page.locator("blockquote").count() == 0
    assert page.locator(".event details").count() == 0
    assert RESULT["events"][0]["quote"] not in page.locator("body").text_content()
    assert RESULT["events"][0]["source"]["context_heading"] not in page.locator("body").text_content()
    page.locator("#generation-info summary").focus()
    page.keyboard.press("Enter")
    assert page.locator("#generation-notice").is_visible()
    assert RESULT["events"][0]["quote"] not in page.locator("body").text_content()
    assert not page.evaluate('Boolean(window.injected)')
    assert page.locator(".event .source-link").get_attribute("rel") == "noopener noreferrer"
    assert '採用を見送った候補' in page.locator('#result-notice').inner_text()
    assert page.locator('#review-notes a').count() == 1
    assert page.locator('#review-notes a').get_attribute('rel') == 'noopener noreferrer'
    assert not page.evaluate('Boolean(window.injected)')
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), ("result", width)
        page.screenshot(path=f"/tmp/timeline-generator-saved-{width}.png", full_page=True)
    # A long timeline and a partial-completion notice must fit all supported widths.
    hundred = RESULT | {'events': [RESULT['events'][0] | {'year': 1800 + i, 'date': f'{1800+i}年', 'title': f'出来事{i+1}'} for i in range(100)], 'stop_reason': 'time_limit', 'notice': '時間上限（10分）により終了しました。検証済みの出来事を保存しています。'}
    job = job | {'result': hundred, 'message': '時間上限により終了しました。検証済みの結果を保存しました。'}
    for width in [320, 375, 414, 768, 1280]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.goto(URL + '/timelines/1')
        page.wait_for_function("document.querySelectorAll('.event').length === 100")
        assert '100件' in page.locator('#result-meta').inner_text()
        assert '時間上限' in page.locator('#result-notice').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('.event').last.scroll_into_view_if_needed()
        assert page.locator('.event h3').last.inner_text() == '出来事100'
        assert page.locator('.event .source-link').count() == 100
        assert page.locator('.event .source-link').first.evaluate('e => e.getBoundingClientRect().height >= 44')
        assert page.locator('blockquote').count() == 0
        assert page.locator('#generation-info').get_attribute('open') is None
        if width == 1280:
            heights = page.locator('.event').evaluate_all('rows => rows.map(e => e.getBoundingClientRect().height)')
            assert max(heights) < 90, heights
            aligned = page.locator('.event').first.evaluate("e => {const cells=[...e.children]; return Math.max(...cells.map(c=>c.getBoundingClientRect().top))-Math.min(...cells.map(c=>c.getBoundingClientRect().top)) < 24;}")
            assert aligned
        page.screenshot(path=f'/tmp/timeline-generator-dense-{width}.png', full_page=False)
    for width in [320, 1280]:
        page.set_viewport_size({'width': width, 'height': 900})
        for path in ['/', '/timelines', '/timelines/1', '/changelog']:
            page.goto(URL + path)
            if path == '/timelines': page.locator('.job-link').wait_for()
            if path == '/timelines/1': page.wait_for_function("document.querySelectorAll('.event').length === 100")
            page.evaluate("document.documentElement.style.fontSize = '200%'")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('text zoom', path, width)
            if path == '/timelines/1':
                page.locator('#generation-info summary').focus()
                page.keyboard.press('Enter')
                assert page.locator('#generation-info').get_attribute('open') is not None
                assert page.locator('#job-status').is_visible() and page.locator('#result-meta').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('open metadata zoom', width)
    # A long heading and saved results must remain readable in active/error states.
    dense_job = job.copy()
    page.set_viewport_size({'width': 320, 'height': 900})
    for state, label in [('queued', '待機中'), ('running', '生成中'), ('failed', '失敗')]:
        job = dense_job | {'query': ('長いテーマと年代条件 ' * 20)[:180], 'state': state, 'stage': 'verify', 'error': 'テスト用の再生成失敗' if state == 'failed' else None}
        page.goto(URL + '/timelines/1')
        page.wait_for_function(f"document.getElementById('job-status').textContent === '{label}'")
        page.evaluate("document.documentElement.style.fontSize = '200%'")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('active/error text zoom', state)
        assert page.locator('#old-result').is_visible()
        if state == 'running': assert page.locator('#progress').is_visible()
        if state == 'failed': assert page.locator('#page-error').is_visible()
    job = dense_job
    page.goto(URL + '/timelines')
    page.locator('.job-link').wait_for()
    assert '時間上限' in page.locator('.job-row .help').inner_text()
    assert page.locator('.job-count').inner_text() == '100件'
    job = job | {'result': RESULT, 'message': '生成が完了しました。'}
    page.goto(URL + '/timelines/1')
    page.wait_for_function("document.querySelectorAll('.event').length === 1")
    old_job = job.copy()
    pending = []
    page.route("**/api/jobs/1", lambda route: pending.append(route))
    import time
    deadline = time.monotonic() + 5
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    assert pending, "poll did not start"
    page.locator("#regenerate").click()
    page.locator("#old-result").wait_for()
    pending.pop(0).fulfill(status=200, content_type="application/json", body=json.dumps(old_job))
    page.wait_for_timeout(300)
    assert page.locator("#job-status").inner_text() == "待機中", "stale poll replaced the action result"
    assert page.locator("#old-result").is_visible()
    page.unroute("**/api/jobs/1")
    assert page.locator(".event").count() == 1
    job = job | {"state": "failed", "error": "テスト用の生成失敗"}
    page.locator("#retry").wait_for()
    assert page.locator(".event").count() == 1
    page.goto(URL + "/timelines")
    page.locator(".job-link").wait_for()
    assert page.locator(".job-count small").inner_text() == "前回"
    assert "前回の" in page.locator(".job-count").get_attribute("aria-label")
    page.goto(URL + "/timelines/1")
    page.locator("#retry").wait_for()
    page.locator("#retry").click()
    page.wait_for_function("document.getElementById('job-status').textContent === '待機中'")
    job = job | {"state": "complete", "result": RESULT | {"events": []}, "generated_at": "2026-10-02T09:01:00+00:00"}
    page.locator("#result-empty").wait_for()
    assert page.locator(".event").count() == 0
    page.goto(URL + "/timelines")
    page.locator(".job-link").wait_for()
    assert page.locator(".job-count").inner_text() == "0件"
    page.locator(".job-link").focus()
    page.wait_for_timeout(3300)
    assert page.locator(".job-link").evaluate("e => e === document.activeElement")
    total = 51
    page.locator("#next").wait_for(state="visible")
    page.wait_for_function("!document.getElementById('next').disabled")
    page.locator("#next").click()
    page.wait_for_function("document.getElementById('list-summary').textContent.includes('51〜51')")
    total = 0
    page.locator("#previous").click()
    page.locator("#list-empty").wait_for()
    page.goto(URL)
    page.locator("#query").fill("エラー")
    page.locator("#submit").click()
    page.locator("#form-error").wait_for()
    assert page.locator("#form-error").inner_text() == "テスト用の接続エラー"
    page.locator("#query").fill(BASE["query"])
    page.locator("#submit").click()
    page.wait_for_url("**/timelines/1")
    page.locator("#result-empty").wait_for()
    page.locator("#refine").click()
    page.wait_for_function("document.getElementById('query').value === 'テストテーマ 1900年以降'")
    assert page.locator("#query").input_value() == BASE["query"]
    assert errors == [], errors
    print("PASS: 5 widths, dense 100 rows, no quote DOM, folded metadata, counts and timeout notice, pages, continued registration, polling, stale poll/action race, saved reuse, retry, regeneration, old result, keyboard, XSS, pagination, empty, errors", flush=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        context.unroute("**/api/jobs**")
        context.unroute('**/*', serve_page)
        for pattern in asset_patterns:
            context.unroute(pattern)
        query = " ".join(sys.argv[2:]) or "インターネット 1980年以降"
        page.goto(URL)
        page.locator("#query").fill(query)
        page.locator("#submit").click()
        page.wait_for_function("location.pathname.startsWith('/timelines/') || document.getElementById('submit')?.disabled === false")
        if not "/timelines/" in page.url:
            assert not page.locator("#form-error").is_visible()
            page.locator("#receipt-link").click()
        page.wait_for_function("document.getElementById('job-status')?.textContent === '完了' || document.getElementById('job-status')?.textContent === '失敗'", timeout=650000)
        assert page.locator("#job-status").inner_text() == "完了", page.locator("#page-error").inner_text()
        assert page.locator(".event").count() > 0, page.locator("#result-notice").inner_text()
        print("LIVE:", query, page.locator("#result-meta").inner_text(), flush=True)
        page.screenshot(path="/tmp/timeline-generator-live.png", full_page=True)
    browser.close()
