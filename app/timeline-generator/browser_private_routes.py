"""Check the shared owner UI with a simulated authenticated API; no live model calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
BASE = "http://localhost:8532"
job = {"id": 1, "query": "テスト", "topic": "テスト", "period": "全期間", "legacy_period": False,
       "state": "queued", "has_result": False, "result": None, "error": None,
       "updated_at": "2026-10-12T00:00:00Z", "generated_at": None, "quality": None,
       "requested_milestones": [], "milestones_revision": 0, "can_delete": False}
calls, errors = [], []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("dialog", lambda dialog: dialog.accept())
    def serve(route):
        global job
        request = route.request
        path = request.url.removeprefix(BASE).split("?")[0]
        if path.startswith("/api/"):
            calls.append((request.method, path))
            assert path.startswith("/api/private/"), path
            if request.method == "POST":
                if path == "/api/private/jobs": job["query"] = json.loads(request.post_data)["query"]
                elif path.endswith("/cancel"): job["state"] = "complete" if job["has_result"] else "cancelled"
                else: job["state"] = "queued"
                data = job
            else: data = {"jobs": [job], "total": 1} if path == "/api/private/jobs" else job
            route.fulfill(content_type="application/json", body=json.dumps(data))
            return
        name = {"/manage": "index.html", "/manage/timelines/1": "detail.html"}.get(path, path.lstrip("/"))
        if name in {"index.html", "detail.html", "app.js", "local-library.js", "styles.css", "tokens.css", "favicon.svg"}:
            mime = "text/html" if name.endswith(".html") else "text/javascript" if name.endswith(".js") else "text/css" if name.endswith(".css") else "image/svg+xml"
            route.fulfill(content_type=mime, body=(ROOT / name).read_bytes())
        else: route.fulfill(status=404, body="")
    context.route("**/*", serve)
    page.goto(BASE + "/manage")
    page.locator("#job-list a").wait_for()
    assert page.locator("#job-list a").get_attribute("href") == "/manage/timelines/1"
    assert page.locator(".wordmark").get_attribute("href") == "/manage"
    assert page.locator('.masthead-nav a[href="/library?from=manage"]').count() == 1
    assert page.locator('.masthead-nav a[href="/changelog?from=manage"]').count() == 1
    page.locator("#query").fill("本人用テスト")
    page.locator("#submit").click()
    page.locator("#receipt").wait_for(state="visible")
    assert page.locator("#receipt-link").get_attribute("href") == "/manage/timelines/1"
    page.locator("#receipt-link").click()
    page.locator("#cancel").wait_for(state="visible")
    assert page.locator("#refine").get_attribute("href").startswith("/manage?query=")
    page.locator("#cancel").click()
    page.locator("#retry").wait_for(state="visible")
    page.locator("#retry").click()
    page.locator("#cancel").wait_for(state="visible")
    job.update(state="complete", has_result=True, generated_at="2026-10-12T00:00:00Z",
               result={"theme": "テスト", "source_mode": "wikipedia", "notice": "", "elapsed_seconds": 1,
                       "events": [{"year": 1926, "date": "1926年", "title": "出来事", "description": "説明",
                                   "source": {"title": "出典", "url": "https://example.org"}}]})
    page.reload()
    page.locator("#regenerate").wait_for(state="visible")
    page.locator("#regenerate").click()
    page.locator("#cancel").wait_for(state="visible")
    for action in ("jobs", "jobs/1/cancel", "jobs/1/retry", "jobs/1/regenerate"):
        assert ("POST", "/api/private/" + action) in calls
    assert not errors, errors
    browser.close()
print("PASS: owner UI keeps list/detail/refine links and generation/cancel/retry/regenerate requests in the private namespace")
