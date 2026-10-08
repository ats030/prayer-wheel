"""Real API, protected preview. No synthetic identity or diagnostic routes."""
import base64
import hmac
import os
from urllib.parse import urlsplit
from workers import asgi, env, Request, Response

for name in ("IKIMONO_SESSION_SECRET", "IKIMONO_PREVIEW_PASSWORD"):
    value = getattr(env, name, None)
    if value is None or not str(value).strip():
        raise RuntimeError(f"{name} binding is required")
for name in ("IKIMONO_SESSION_SECRET", "IKIMONO_ALLOWED_HOSTS", "IKIMONO_PUBLIC_ORIGIN"):
    value = getattr(env, name, None)
    if value is not None:
        os.environ[name] = str(value)
os.environ["IKIMONO_PUBLIC_MODE"] = "1"
os.environ["IKIMONO_BACKGROUND_JOBS"] = "0"
os.environ["IKIMONO_BROWSER_PHOTOS"] = "1"

import bundled_resources
from _resources import RESOURCES, BUNDLE_SHA256
bundled_resources.configure(RESOURCES)
import main
from fastapi.routing import APIRoute, request_response
app = main.app

def cached_form_handler(handler):
    async def handle(request):
        if "preview_form" in request.scope:
            request._form = request.scope["preview_form"]
        return await handler(request)
    return handle

for route in app.routes:
    if isinstance(route, APIRoute) and route.path == "/identify":
        route.app = request_response(cached_form_handler(route.get_route_handler()))

class Default(asgi.entrypoint(app)):
    async def fetch(self, request):
        expected = "Basic " + base64.b64encode(
            ("preview:" + str(self.env.IKIMONO_PREVIEW_PASSWORD)).encode()).decode()
        provided = request.headers.get("authorization", "")
        # Bytes comparison also rejects non-ASCII credentials without raising.
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            return Response("Authentication required", status=401, headers={
                "WWW-Authenticate": 'Basic realm="ikimono-note preview", charset="UTF-8"',
                "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow",
            })
        # Remote upload validation exposes startup strings, but not a live D1
        # handle. Require the runtime binding before serving authenticated work.
        if getattr(self.env, "DB", None) is None:
            return Response("Database unavailable", status=503, headers={"Cache-Control": "no-store"})
        path = urlsplit(request.url).path
        if path.startswith("/probe/"):
            return Response("Not found", status=404)
        if path.startswith("/vendor/photo/sources/"):
            result = await self.env.ASSETS.fetch(request.js_object)
        elif path == "/identify" and request.method == "POST":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 6 * 1024 * 1024 + 16384:
                if request.body is not None:
                    # Finish the incoming stream without retaining bytes. The
                    # local proxy otherwise resets a still-uploading client
                    # before it can receive the size-error response.
                    reader = request.body.getReader()
                    try:
                        while not (await reader.read()).done:
                            pass
                    finally:
                        reader.releaseLock()
                return Response("Bounded Content-Length required", status=400)
            try:
                form = await request.form_data()
            except (TypeError, ValueError):
                return Response("Invalid multipart form", status=400)
            files = form.get_all("files")
            if not 1 <= len(files) <= 3 or any(isinstance(f, str) or f.size > 2 * 1024 * 1024 for f in files):
                return Response("Invalid photos", status=400)
            import io
            from starlette.datastructures import FormData, UploadFile, Headers
            items = []
            for name, value in form.items():
                if isinstance(value, str):
                    if len(value) > 8192:
                        return Response("Oversize field", status=400)
                else:
                    if name != "files":
                        return Response("Unexpected file", status=400)
                    raw = await value.bytes()
                    value = UploadFile(io.BytesIO(raw), size=len(raw), filename=value.name,
                                       headers=Headers({"content-type": value.content_type}))
                items.append((name, value))
            parsed = FormData(items)
            async def cached_app(scope, receive, send):
                scope["preview_form"] = parsed
                await app(scope, receive, send)
            forwarded = Request(request.url, method="POST", headers=dict(request.headers.items()))
            result = await asgi.fetch(cached_app, forwarded, self.env, self.ctx)
        else:
            result = await super().fetch(request)
        import js
        # Copy the native response before changing potentially immutable asset
        # headers, preserving repeated Set-Cookie values and the body stream.
        native = result.js_object if isinstance(result, Response) else result
        response = js.Response.new(native.body, native)
        response.headers.set("X-Robots-Tag", "noindex, nofollow")
        response.headers.set("Cache-Control", "no-store")
        if path == "/health":
            response.headers.set("X-Preview-Bundle-SHA256", BUNDLE_SHA256)
        return Response(response)
