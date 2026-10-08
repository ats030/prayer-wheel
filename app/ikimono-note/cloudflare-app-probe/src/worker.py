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
# Startup-only experiment. The browser upload path is not integrated yet.
os.environ["IKIMONO_BROWSER_PHOTOS"] = "1"

import bundled_resources
from _resources import RESOURCES, BUNDLE_SHA256

bundled_resources.configure(RESOURCES)
from main import app


@app.middleware("http")
async def probe_revision(request, call_next):
    response = await call_next(request)
    if request.url.path == "/health":
        response.headers["X-Probe-Bundle-SHA256"] = BUNDLE_SHA256
    return response


Default = asgi.entrypoint(app)
