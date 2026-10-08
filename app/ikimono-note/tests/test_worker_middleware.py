"""Compare Workers adapters with the original application policies, without I/O."""
import sys
from copy import copy
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

sys.path.insert(0, str(Path(__file__).parents[1]))
import main
from worker_middleware import GatePolicy, HeaderPolicy, prepare


@pytest.fixture
def pair(monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "CANONICAL_HOST", "canonical.example")
    monkeypatch.setattr(main, "ALLOWED_HOSTS", ["localhost", "alias.example", "canonical.example"])
    monkeypatch.setattr(main.auth, "PUBLIC_ORIGIN", "https://canonical.example")
    monkeypatch.setattr(main.auth, "configured", lambda: True)
    monkeypatch.setattr(main.auth, "read_session", lambda cookie: {"sub": "synthetic"} if cookie == "synthetic-session" else None)
    monkeypatch.setattr(main, "trial_enabled", lambda: False)
    original = FastAPI()
    original.add_middleware(TrustedHostMiddleware, allowed_hosts=main.ALLOWED_HOSTS)
    for policy in (main.keep_one_origin, main.require_login, main.security_headers):
        original.middleware("http")(policy)

    @original.api_route("/{path:path}", methods=["GET", "POST"])
    async def downstream(request: Request, path: str):
        if request.query_params.get("stream"):
            async def chunks():
                yield b"first\x00"
                yield b"second\xff"
            return StreamingResponse(chunks(), media_type="application/octet-stream")
        response = Response(await request.body() if request.method == "POST" else b"downstream",
                            headers={"Cache-Control": "private, max-age=0"})
        response.set_cookie("flow", "synthetic-flow", secure=True, httponly=True, samesite="lax")
        response.set_cookie("session", "synthetic-value", secure=True, httponly=True, samesite="lax")
        return response

    optimized = copy(original)
    prepare(optimized, main)
    assert optimized.user_middleware is not original.user_middleware
    return original, optimized


@pytest.mark.parametrize("path,host,logged_in,trial,method", [
    ("/health", "localhost", False, False, "GET"),
    ("/health?stream=1", "localhost", False, False, "GET"),
    ("/vendor/fixed.js", "localhost", False, False, "GET"),
    ("/api/private", "localhost", False, False, "GET"),
    ("/history", "localhost", False, False, "GET"),
    ("/", "localhost", False, False, "GET"),
    ("/history", "localhost", True, False, "GET"),
    ("/identify", "localhost", True, False, "POST"),
    ("/identify", "localhost", False, True, "POST"),
    ("/api/photo-original", "localhost", False, True, "POST"),
    ("/health?next=%2Fhistory&x=1", "alias.example", False, False, "GET"),
    ("/history", "alias.example", True, False, "GET"),
    ("/health", "untrusted.example", False, False, "GET"),
    ("/history", "untrusted.example", True, False, "GET"),
])
def test_original_policy_response_parity(pair, monkeypatch, path, host, logged_in, trial, method):
    monkeypatch.setattr(main, "trial_enabled", lambda: trial)
    headers = {"host": host}
    if logged_in:
        headers["cookie"] = main.auth.SESSION_COOKIE + "=synthetic-session"
    results = []
    for app in pair:
        with TestClient(app, base_url="http://localhost", follow_redirects=False) as client:
            response = client.request(method, path, headers=headers,
                                      content=b"photo\x00\xffunchanged" if method == "POST" else None)
            results.append((response.status_code, response.content, sorted(response.headers.multi_items())))
    assert results[0] == results[1]
    status, body, headers = results[1]
    assert ("x-frame-options", "DENY") in headers
    if method == "POST":
        assert status == 200 and body == b"photo\x00\xffunchanged"
    if body == b"downstream":
        assert len([item for item in headers if item[0] == "set-cookie"]) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("adapter", [GatePolicy, HeaderPolicy])
@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
async def test_non_http_is_forwarded_without_policy(adapter, scope_type):
    seen = []
    async def downstream(scope, receive, send):
        seen.append(scope)
    async def forbidden(*args):
        raise AssertionError("HTTP policy must not run")
    scope = {"type": scope_type}
    await adapter(downstream, forbidden)(scope, None, None)
    assert seen == [scope]


def test_changed_policy_registration_fails_at_startup():
    app = FastAPI()
    app.middleware("http")(main.security_headers)
    with pytest.raises(RuntimeError, match="policies were not found"):
        prepare(app, main)
