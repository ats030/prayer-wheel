"""Local full-app startup probe, not a production deployment configuration."""
import os
from workers import asgi, env

# auth and main read configuration at import. Require a fixed secret instead
# of trying forbidden startup randomness or silently accepting a missing DB.
secret = getattr(env, "IKIMONO_SESSION_SECRET", None)
if secret is None or not str(secret).strip():
    raise RuntimeError("IKIMONO_SESSION_SECRET binding is required")
for name in (
    "IKIMONO_SESSION_SECRET", "IKIMONO_ALLOWED_HOSTS", "IKIMONO_PUBLIC_ORIGIN",
    "IKIMONO_GOOGLE_CLIENT_ID", "IKIMONO_GOOGLE_CLIENT_SECRET",
):
    value = getattr(env, name, None)
    if value is not None:
        os.environ[name] = str(value)
if getattr(env, "DB", None) is None:
    raise RuntimeError("DB binding is required")
os.environ["IKIMONO_PUBLIC_MODE"] = "1"
os.environ["IKIMONO_BACKGROUND_JOBS"] = "0"
# Local experiment: browser preparation keeps native image CPU off Workers.
os.environ["IKIMONO_BROWSER_PHOTOS"] = "1"

import bundled_resources
from _resources import RESOURCES, BUNDLE_SHA256

bundled_resources.configure(RESOURCES)
import main
app = main.app

# A request-local form cache lets the isolated comparison reuse the exact
# existing FastAPI validation and identification handler after native parsing.
# Requests without this internal scope value follow the original route.
from fastapi.routing import APIRoute, request_response
SYNTHETIC_AI = str(getattr(env, "IKIMONO_SYNTHETIC_AI", "")) == "1"
PROFILE_IO = SYNTHETIC_AI and str(getattr(env, "IKIMONO_PROFILE_IO", "")) == "1"

if PROFILE_IO:
    from copy import copy
    import worker_middleware
    from fastapi import FastAPI
    from fastapi.middleware.asyncexitstack import AsyncExitStackMiddleware
    runtime_app = FastAPI()
    # FastAPI requires its file-cleanup stack even without app middleware.
    runtime_router = AsyncExitStackMiddleware(app.router)
    runtime_optimized = copy(app)
    worker_middleware.prepare(runtime_optimized, main)

    @runtime_app.get("/async-health")
    async def runtime_async_health():
        return {"ok": True}

    @runtime_app.get("/sync-health")
    def runtime_sync_health():
        return {"ok": True}

    async def runtime_asgi_health(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"ok":true}'})


def cached_form_handler(handler):
    async def handle(request):
        if "profile_form" in request.scope:
            request._form = request.scope["profile_form"]
        return await handler(request)
    return handle


for route in app.routes:
    if PROFILE_IO and isinstance(route, APIRoute) and route.path == "/identify":
        route.app = request_response(cached_form_handler(route.get_route_handler()))

if SYNTHETIC_AI:
    from hashlib import sha256

    def synthetic_identify(images, **context):
        return {"category": "動物", "summary": "合成検証", "model": context["model"],
                "provider": context["provider"], "candidates": [{
                    "common_name_ja": "合成候補", "scientific_name": "Acheilognathus longipinnis",
                    "confidence": 30, "traits": ["合成特徴"], "uncertainty": "合成検証",
                }], "probe": {"sha256": [sha256(raw).hexdigest() for raw in images],
                              "location": context["location"], "observed_date": context["observed_date"]}}

    main.pipeline.identify_all = synthetic_identify
    main.vision._lookup_taxon = lambda name: [{"name": name, "preferred_common_name": "イタセンパラ",
                                              "rank": "species", "id": 0}]

    def forbid_pixel_processing(*args, **kwargs):
        raise AssertionError("Workers photo routes must not decode pixels")
    main.vision.prepare_image = forbid_pixel_processing
    main.vision.extract_exif_context = forbid_pixel_processing
    main.image_quality.judge = forbid_pixel_processing


class Default(asgi.entrypoint(app)):
    async def fetch(self, request):
        from urllib.parse import urlsplit
        url = urlsplit(request.url)
        if not url.path.startswith("/probe/profile/"):
            result = await super().fetch(request)
            if url.path == "/health":
                import js
                from workers import Response
                native = result.js_object if isinstance(result, Response) else result
                response = js.Response.new(native.body, native)
                response.headers.set("X-Probe-Bundle-SHA256", BUNDLE_SHA256)
                response.headers.set("X-Probe-Synthetic-AI", "1" if SYNTHETIC_AI else "0")
                response.headers.set("X-Probe-Profile-IO", "1" if PROFILE_IO else "0")
                return Response(response)
            return result
        from workers import Response
        if (not PROFILE_IO
                or url.hostname not in {"localhost", "127.0.0.1"}
                or request.headers.get("host", "").split(":")[0] not in {"localhost", "127.0.0.1"}):
            return Response.from_json({"error": "Local synthetic profiling only"}, status=403)
        # These paths never use real identities or arbitrary database keys.
        # Do not publish this local harness or enable this flag in production.
        from hashlib import sha256
        if url.path == "/probe/profile/native-health" and request.method == "GET":
            return Response.from_json({"ok": True})
        runtime_routes = {
            "/probe/profile/asgi-health": (runtime_asgi_health, "/health"),
            "/probe/profile/fastapi-async-health": (runtime_app, "/async-health"),
            "/probe/profile/fastapi-sync-health": (runtime_app, "/sync-health"),
            "/probe/profile/router-health": (runtime_router, "/health"),
            "/probe/profile/router-me": (runtime_router, "/api/me"),
            "/probe/profile/full-health": (app, "/health"),
            "/probe/profile/full-me": (app, "/api/me"),
            "/probe/profile/optimized-health": (runtime_optimized, "/health"),
            "/probe/profile/optimized-me": (runtime_optimized, "/api/me"),
        }
        if url.path in runtime_routes and request.method == "GET":
            from workers import Request
            target, path = runtime_routes[url.path]
            forwarded = Request(f"{url.scheme}://{url.netloc}{path}",
                                headers=dict(request.headers.items()))
            return await asgi.fetch(target, forwarded, self.env, self.ctx)
        if url.path == "/probe/profile/gemini-template" and request.method == "GET":
            # Small template from the actual provider function, no copied prompt
            # or independent generation settings and no external HTTP call.
            import types
            import httpx
            captured = []

            def capture_template(target, *, json, headers, timeout):
                captured.append(json)
                return httpx.Response(200, request=httpx.Request("POST", target), json={"candidates": [{
                    "content": {"parts": [{"text": '{"category":"動物","candidates":[]}'}]}
                }]})

            original = main.vision.identify_gemini
            shim = types.SimpleNamespace(post=capture_template, HTTPStatusError=httpx.HTTPStatusError,
                                         HTTPError=httpx.HTTPError)
            provider = types.FunctionType(original.__code__, {**original.__globals__, "httpx": shim},
                                          original.__name__, original.__defaults__, original.__closure__)
            provider.__kwdefaults__ = original.__kwdefaults__
            provider([b""], "synthetic-key", "gemini-3.5-flash-lite")
            assert captured[0]["contents"][0]["parts"][0]["inline_data"]["data"] == ""
            return Response.from_json({"template": captured[0], "network_calls": 0})
        if url.path in {"/probe/profile/native-upload", "/probe/profile/native-identify", "/probe/profile/native-gemini-payload", "/probe/profile/native-gemini-payload-checked", "/probe/profile/native-gemini-payload-js", "/probe/profile/native-gemini-payload-js-checked"} and request.method == "POST":
            length = request.headers.get("content-length", "")
            if not length.isdigit() or int(length) > 6 * 1024 * 1024 + 16384:
                return Response.from_json({"error": "Bounded Content-Length required"}, status=400)
            form = await request.form_data()
            files = form.get_all("files")
            if not 1 <= len(files) <= 3 or any(isinstance(file, str) or file.size > 2 * 1024 * 1024 for file in files):
                return Response.from_json({"error": "Invalid synthetic files"}, status=400)
            if "/native-gemini-payload" in url.path:
                # Run the real provider's payload construction and HTTPX JSON
                # serialization without a network call or global monkeypatch.
                import base64
                import json
                import types
                import httpx
                captured = []
                native_encoding = "payload-js" in url.path
                if native_encoding:
                    import js
                    from pyodide.ffi import to_js

                    class EncodedASCII:
                        def __init__(self, raw):
                            self.value = to_js(raw).toBase64()

                        def decode(self, encoding):
                            assert encoding == "ascii"
                            return self.value

                    encoding = types.SimpleNamespace(b64encode=EncodedASCII)
                else:
                    encoding = base64

                def synthetic_post(target, *, json, headers, timeout):
                    if native_encoding:
                        serialized = js.JSON.stringify(to_js(json, dict_converter=js.Object.fromEntries))
                        # Include the same Python boundary and HTTPX Request cost.
                        # The checked twin additionally verifies semantic parity.
                        outgoing = httpx.Request("POST", target, content=serialized.encode(), headers=headers)
                    else:
                        outgoing = httpx.Request("POST", target, json=json, headers=headers)
                    captured.append(outgoing.content)
                    return httpx.Response(200, request=outgoing, json={"candidates": [{
                        "content": {"parts": [{"text": '{"category":"動物","candidates":[]}'}]}
                    }]})

                shim = types.SimpleNamespace(post=synthetic_post, HTTPStatusError=httpx.HTTPStatusError,
                                             HTTPError=httpx.HTTPError)
                original = main.vision.identify_gemini
                provider = types.FunctionType(original.__code__, {**original.__globals__, "httpx": shim, "base64": encoding},
                                              original.__name__, original.__defaults__, original.__closure__)
                provider.__kwdefaults__ = original.__kwdefaults__
                images = [await file.bytes() for file in files]
                provider(images, "synthetic-key", "gemini-3.5-flash-lite")
                wire = captured[0]
                if url.path.endswith("-checked"):
                    parts = json.loads(wire)["contents"][0]["parts"]
                    recovered = [base64.b64decode(part["inline_data"]["data"], validate=True)
                                 for part in parts if "inline_data" in part]
                    assert recovered == images, "Provider serialization changed photo bytes"
                    if native_encoding:
                        baseline = []

                        def baseline_post(target, *, json, headers, timeout):
                            outgoing = httpx.Request("POST", target, json=json, headers=headers)
                            baseline.append(outgoing.content)
                            return httpx.Response(200, request=outgoing, json={"candidates": [{
                                "content": {"parts": [{"text": '{"category":"動物","candidates":[]}'}]}
                            }]})

                        baseline_shim = types.SimpleNamespace(post=baseline_post, HTTPStatusError=httpx.HTTPStatusError,
                                                              HTTPError=httpx.HTTPError)
                        baseline_provider = types.FunctionType(original.__code__,
                            {**original.__globals__, "httpx": baseline_shim}, original.__name__,
                            original.__defaults__, original.__closure__)
                        baseline_provider.__kwdefaults__ = original.__kwdefaults__
                        baseline_provider(images, "synthetic-key", "gemini-3.5-flash-lite")
                        assert json.loads(wire) == json.loads(baseline[0]), "Provider prompt/config/photo payload changed"
                return Response.from_json({"probe": {"sha256": [sha256(raw).hexdigest() for raw in images]},
                                           "wire_bytes": len(wire), "wire_sha256": sha256(wire).hexdigest(),
                                           "network_calls": 0})
            if url.path.endswith("native-identify"):
                import io
                from workers import Request
                from starlette.datastructures import FormData, UploadFile, Headers
                items = []
                for name, value in form.items():
                    if isinstance(value, str):
                        if len(value) > 8192:
                            return Response.from_json({"error": "Oversize synthetic field"}, status=400)
                    else:
                        if name != "files":
                            return Response.from_json({"error": "Unexpected synthetic file"}, status=400)
                        raw = await value.bytes()
                        value = UploadFile(io.BytesIO(raw), size=len(raw), filename=value.name,
                                           headers=Headers({"content-type": value.content_type}))
                    items.append((name, value))
                parsed = FormData(items)

                async def cached_app(scope, receive, send):
                    scope["profile_form"] = parsed
                    await app(scope, receive, send)

                forwarded = Request(f"{url.scheme}://{url.netloc}/identify", method="POST",
                                    headers=dict(request.headers.items()))
                return await asgi.fetch(cached_app, forwarded, self.env, self.ctx)
            hashes = [sha256(await file.bytes()).hexdigest() for file in files]
            return Response.from_json({"probe": {"sha256": hashes}})
        parts = url.path.split("/")
        if len(parts) == 6 and parts[3] == "d1" and parts[4] in {"blob", "hex"}:
            import d1_store
            store = d1_store.D1Store(self.env.DB)
            mode, action = parts[4:]
            token = "synthetic-profile-" + mode
            photo = bytes([37]) * (700 * 1024)
            if action == "write" and request.method == "POST":
                value = photo if mode == "blob" else photo.hex()
                expression = "?" if mode == "blob" else "unhex(?)"
                await store.statement(
                    "INSERT INTO shares(token,owner,created_at,payload,photo,photo_type) "
                    f"VALUES(?,?,?,?,{expression},?)",
                    token, "synthetic-profile", "2001-01-01T00:00:00Z", '{"synthetic":true}', value,
                    "image/png").run()
                return Response.from_json({"ok": True})
            if action == "read" and request.method == "GET":
                if mode == "blob":
                    value = await store.share_photo(token)
                    raw = value[0] if value else b""
                else:
                    row = await store.statement("SELECT hex(photo) AS encoded FROM shares WHERE token=?", token).first()
                    raw = bytes.fromhex(row.encoded) if row else b""
                return Response.from_json({"photo_bytes": len(raw), "sha256": sha256(raw).hexdigest()})
            if action == "delete" and request.method == "POST":
                await store.delete_share(token, "synthetic-profile")
                return Response.from_json({"ok": True})
        return Response.from_json({"error": "Unknown synthetic operation"}, status=404)
