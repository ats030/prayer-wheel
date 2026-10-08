"""Workers-only ASGI adapters for the existing, unchanged header/gate policies."""
from types import SimpleNamespace

from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class HeaderPolicy:
    def __init__(self, app, dispatch):
        self.app, self.dispatch = app, dispatch

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                response = SimpleNamespace(headers=MutableHeaders(scope=message))

                async def response_only(_request):
                    return response

                result = await self.dispatch(request, response_only)
                if result is not response:
                    raise RuntimeError("Header policy must return the same response")
            await send(message)

        await self.app(scope, receive, with_headers)


class GatePolicy:
    def __init__(self, app, dispatch):
        self.app, self.dispatch = app, dispatch

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        allowed = object()

        async def allow(_request):
            return allowed

        # These two policies inspect only URL, headers, cookies and config.
        # They do not consume request bodies or modify downstream responses.
        decision = await self.dispatch(Request(scope, receive), allow)
        if decision is allowed:
            await self.app(scope, receive, send)
        else:
            await decision(scope, receive, send)


def prepare(app, policies):
    """Replace exactly the three reviewed policies, preserving order and logic."""
    replacements = {
        policies.security_headers: HeaderPolicy,
        policies.require_login: GatePolicy,
        policies.keep_one_origin: GatePolicy,
    }
    middleware = []
    found = set()
    for item in app.user_middleware:
        dispatch = item.kwargs.get("dispatch")
        if item.cls is BaseHTTPMiddleware and dispatch in replacements:
            if item.args or set(item.kwargs) != {"dispatch"} or dispatch in found:
                raise RuntimeError("Unexpected policy middleware configuration")
            middleware.append(Middleware(replacements[dispatch], dispatch=dispatch))
            found.add(dispatch)
        else:
            middleware.append(item)
    if found != set(replacements):
        raise RuntimeError("Expected header/login/origin policies were not found")
    app.user_middleware = middleware
    app.middleware_stack = app.build_middleware_stack()
