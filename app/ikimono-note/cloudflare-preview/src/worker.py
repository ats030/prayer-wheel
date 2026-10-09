"""Real API, protected preview. No synthetic identity or diagnostic routes."""
import base64
import hmac
import json
import os
from urllib.parse import unquote, urlsplit
from workers import asgi, env, Request, Response

for name in ("IKIMONO_SESSION_SECRET", "IKIMONO_PREVIEW_PASSWORD"):
    value = getattr(env, name, None)
    if value is None or not str(value).strip():
        raise RuntimeError(f"{name} binding is required")
for name in ("IKIMONO_SESSION_SECRET", "IKIMONO_ALLOWED_HOSTS", "IKIMONO_PUBLIC_ORIGIN",
             "IKIMONO_GOOGLE_CLIENT_ID", "IKIMONO_GOOGLE_CLIENT_SECRET",
             "IKIMONO_GEMINI_MAX_OUTPUT_TOKENS", "IKIMONO_GEMINI_THINKING_LEVEL"):
    value = getattr(env, name, None)
    if value is not None:
        os.environ[name] = str(value)
os.environ["IKIMONO_PUBLIC_MODE"] = "1"
os.environ["IKIMONO_BACKGROUND_JOBS"] = "0"
os.environ["IKIMONO_BROWSER_PHOTOS"] = "1"
os.environ["IKIMONO_NATIVE_TRANSPORT"] = str(getattr(env, "IKIMONO_NATIVE_TRANSPORT", ""))
os.environ["IKIMONO_BROWSER_GEMINI"] = str(getattr(env, "IKIMONO_BROWSER_GEMINI", ""))

import bundled_resources
from _resources import RESOURCES, BUNDLE_SHA256, NATIVE_ASSET_PATHS, NATIVE_ASSET_LENGTHS
bundled_resources.configure(RESOURCES)
import main
from fastapi.routing import APIRoute, request_response
app = main.app
# Ephemeral per-isolate observations, never persisted or shared with users.
_probe_isolate_id = None
_invocation_count = 0

def cached_form_handler(handler):
    async def handle(request):
        if "preview_form" in request.scope:
            request._form = request.scope["preview_form"]
        return await handler(request)
    return handle

for route in app.routes:
    if isinstance(route, APIRoute) and route.path == "/identify":
        route.app = request_response(cached_form_handler(route.get_route_handler()))

# Keep lazy library imports and stack construction in the deployment snapshot,
# rather than paying for them in the first authenticated ASGI request. Reuse the
# pinned AnyIO resolver; this imports its backend without starting an event loop.
from anyio._core._eventloop import get_async_backend
get_async_backend("asyncio")
import worker_middleware
worker_middleware.prepare(app, main)

class Default(asgi.entrypoint(app)):
    async def fetch(self, request):
        global _probe_isolate_id, _invocation_count
        _invocation_count += 1
        invocation = _invocation_count
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
        path = unquote(urlsplit(request.url).path)
        if path.startswith("/probe/"):
            return Response("Not found", status=404)
        native_asset = path in NATIVE_ASSET_PATHS
        if native_asset:
            host = request.headers.get("host", urlsplit(request.url).netloc).split(":")[0]
            if host not in main.ALLOWED_HOSTS:
                result = Response("Invalid host header", status=400)
            elif request.method not in {"GET", "HEAD"}:
                result = Response("Method not allowed", status=405, headers={"Allow": "GET, HEAD"})
            else:
                result = await self.env.ASSETS.fetch(request.js_object)
        elif path == "/identify" and request.method == "POST":
            length = request.headers.get("content-length", "")
            body_limit = 9 * 1024 * 1024 if main.NATIVE_TRANSPORT else 6 * 1024 * 1024 + 16384
            if not length.isdigit() or int(length) > body_limit:
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
            native_payloads = form.get_all("provider_payload")
            native_payload = None
            if native_payloads:
                if len(native_payloads) != 1 or files or isinstance(native_payloads[0], str):
                    return Response("Invalid payload", status=400)
                native_payload = native_payloads[0]
                if native_payload.content_type != "application/json" or not 0 < native_payload.size <= 3 * 2796204 + 32768:
                    return Response("Invalid payload", status=400)
            elif (int(length) > 6 * 1024 * 1024 + 16384 or not 1 <= len(files) <= 3
                  or any(isinstance(f, str) or f.size > 2 * 1024 * 1024 for f in files)):
                return Response("Invalid photos", status=400)
            import io
            from starlette.datastructures import FormData, UploadFile, Headers
            items = []
            native_fields = {"background", "location", "observed_date", "size", "verify_names", "use_plantnet",
                             "request_provider", "request_model", "request_api_key", "request_plantnet_key", "client_photos"}
            seen = set()
            for name, value in form.items():
                if native_payload is not None:
                    if name == "provider_payload":
                        continue
                    if name not in native_fields or name in seen:
                        return Response("Unexpected field", status=400)
                    seen.add(name)
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
                if native_payload is not None:
                    async def native_identify(template, count, model, api_key):
                        from workers import import_from_javascript
                        transport = import_from_javascript("worker_transport.mjs")
                        reply = await transport.identify(native_payload.js_object,
                            json.dumps(template, ensure_ascii=False), count, model, api_key)
                        return json.loads(str(reply))
                    scope["native_identify"] = native_identify
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
        marker = request.headers.get("X-Ikimono-CPU-Probe", "")
        if len(marker) == 8 and all(char in "0123456789abcdef" for char in marker):
            if _probe_isolate_id is None:
                # Randomness runs in request context, never in the snapshot.
                _probe_isolate_id = str(js.crypto.randomUUID())
            response.headers.set("X-Preview-Isolate", _probe_isolate_id)
            response.headers.set("X-Preview-Isolate-Invocation", str(invocation))
        if native_asset:
            if request.method == "HEAD" and response.status == 200:
                response.headers.set("Content-Length", str(NATIVE_ASSET_LENGTHS[path]))
            if path.startswith("/downloads/") and response.status in {200, 206}:
                response.headers.set("Content-Disposition", 'attachment; filename="' + path.rsplit("/", 1)[1] + '"')
            response.headers.set("X-Content-Type-Options", "nosniff")
            response.headers.set("X-Frame-Options", "DENY")
            response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.set("Permissions-Policy", "camera=(self), geolocation=(self)")
            response.headers.set("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
            response.headers.set("Content-Security-Policy", main.CONTENT_SECURITY_POLICY)
        if path == "/health":
            response.headers.set("X-Preview-Bundle-SHA256", BUNDLE_SHA256)
        return Response(response)
