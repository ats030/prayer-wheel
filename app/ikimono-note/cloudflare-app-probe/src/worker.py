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
import main
app = main.app

SYNTHETIC_AI = str(getattr(env, "IKIMONO_SYNTHETIC_AI", "")) == "1"
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


@app.middleware("http")
async def probe_revision(request, call_next):
    response = await call_next(request)
    if request.url.path == "/health":
        response.headers["X-Probe-Bundle-SHA256"] = BUNDLE_SHA256
        response.headers["X-Probe-Synthetic-AI"] = "1" if SYNTHETIC_AI else "0"
    return response


Default = asgi.entrypoint(app)
