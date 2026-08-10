"""species-explorer: photograph-based local species identification (port 8523)."""

from collections import defaultdict, deque
from pathlib import Path
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

import config_store
import creators_api
import vision

class SettingsUpdate(BaseModel):
    provider: str
    models: dict[str, str] = Field(default_factory=dict)
    local_llm: dict[str, object] | None = None
    api_keys: dict[str, str | None] = Field(default_factory=dict)
    delete_keys: list[str] = Field(default_factory=list)
    affiliate: dict[str, object] = Field(default_factory=dict)


app = FastAPI(title="Species Explorer")
STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_MODE = os.getenv("SPECIES_PUBLIC_MODE", "").lower() in {"1", "true", "yes"}
PUBLIC_LOCAL_ENABLED = os.getenv("SPECIES_PUBLIC_LOCAL", "").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [host.strip() for host in os.getenv("SPECIES_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
if PUBLIC_MODE:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_RATE_LOCK = threading.Lock()


def _rate_limit(request: Request, scope: str, limit: int, window: int = 60) -> None:
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    key = (client, scope)
    with _RATE_LOCK:
        bucket = _RATE_BUCKETS[key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(status_code=429, detail="しばらく待ってから再試行してください", headers={"Retry-After": str(window)})
        bucket.append(now)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self)"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings", include_in_schema=False)
def settings() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")

@app.get("/history", include_in_schema=False)
def history() -> FileResponse:
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/privacy", include_in_schema=False)
def privacy() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/terms", include_in_schema=False)
def terms() -> FileResponse:
    return FileResponse(STATIC_DIR / "terms.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/settings")
def get_settings() -> dict[str, object]:
    result = config_store.public()
    result["public_mode"] = PUBLIC_MODE
    if PUBLIC_MODE:
        result["local_llm"] = {"url": ""}
        result["api_key_configured"] = {
            provider: False for provider in ("openai", "anthropic", "gemini", "plantnet")
        }
        if not PUBLIC_LOCAL_ENABLED:
            result["available_models"]["local"] = []
            if result["provider"] == "local":
                result["provider"] = "gemini"
    return result


@app.post("/api/settings")
def save_settings(update: SettingsUpdate) -> dict[str, object]:
    if PUBLIC_MODE:
        raise HTTPException(status_code=403, detail="公開版ではサーバー設定を変更できません")
    try:
        return config_store.save(
            provider=update.provider,
            models=update.models,
            local_llm=update.local_llm,
            api_keys=update.api_keys,
            delete_keys=update.delete_keys,
            affiliate=update.affiliate,
        )
    except config_store.SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/affiliate/impression")
def affiliate_impression() -> dict[str, bool]:
    try:
        settings = config_store.load()
        if not settings["affiliate"]["enabled"]:
            raise LookupError("広告が設定されていません")
        config_store.record_affiliate("impressions")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/affiliate/click")
def affiliate_click(q: str = "") -> RedirectResponse:
    try:
        target = config_store.affiliate_target(q)
        config_store.record_affiliate("clicks")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(target, status_code=302)


@app.post("/api/affiliate/click")
def affiliate_click_event() -> dict[str, bool]:
    if not config_store.load()["affiliate"]["enabled"]:
        raise HTTPException(status_code=404, detail="広告が設定されていません")
    config_store.record_affiliate("clicks")
    return {"ok": True}


@app.get("/api/amazon/products")
async def amazon_products(q: str = "") -> JSONResponse:
    settings = config_store.load()
    affiliate = settings["affiliate"]
    keys = settings["api_keys"]
    if not affiliate.get("product_enabled"):
        raise HTTPException(status_code=404, detail="商品APIが設定されていません")
    try:
        products = await run_in_threadpool(creators_api.search_products, q, keys.get("amazon_creators_id", ""), keys.get("amazon_creators_secret", ""), affiliate.get("partner_tag", ""), 4)
    except creators_api.CreatorsAPIError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not products:
        raise HTTPException(status_code=404, detail="関連商品が見つかりません")
    return JSONResponse({"products": products})


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "model": vision.MODEL, "local_processing": True, "providers": ["local", "openai", "anthropic", "gemini"]}


@app.post("/api/photo-metadata")
async def photo_metadata(request: Request, files: list[UploadFile] = File(default=[])) -> dict[str, object]:
    if PUBLIC_MODE:
        _rate_limit(request, "metadata", 20)
    if not files or len(files) > 3:
        raise HTTPException(status_code=400, detail="写真は1〜3枚選んでください")
    metadata: dict[str, object] = {}
    for upload in files:
        if upload.content_type and not upload.content_type.startswith("image/"):
            raise HTTPException(status_code=415, detail="画像ファイルを選んでください")
        raw = await upload.read(vision.MAX_UPLOAD_BYTES + 1)
        if len(raw) > vision.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="画像は1枚15MB以下にしてください")
        try:
            await run_in_threadpool(vision.prepare_image, raw)
        except vision.VisionError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        extracted = await run_in_threadpool(vision.extract_exif_context, raw)
        for key, value in extracted.items():
            metadata.setdefault(key, value)
    return metadata


@app.post("/identify")
async def identify(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    file: UploadFile | None = File(default=None),
    location: str = Form(default=""),
    observed_date: str = Form(default=""),
    size: str = Form(default=""),
    verify_names: bool = Form(default=False),
    use_plantnet: bool = Form(default=False),
    request_provider: str = Form(default=""),
    request_model: str = Form(default=""),
    request_api_key: str = Form(default=""),
    request_plantnet_key: str = Form(default=""),
) -> JSONResponse:
    if PUBLIC_MODE:
        _rate_limit(request, "identify", 6)
    settings = config_store.load()
    provider = request_provider if PUBLIC_MODE else settings["provider"]
    if provider not in config_store.MODELS:
        raise HTTPException(status_code=400, detail="計算資源を選び直してください")
    if PUBLIC_MODE and provider == "local" and not PUBLIC_LOCAL_ENABLED:
        raise HTTPException(status_code=403, detail="公開版のローカルLLMは現在利用できません")
    if PUBLIC_MODE:
        model = request_model
        catalog, _ = config_store.model_catalog(
            settings["models"]["local"],
            (settings.get("local_llm") or {}).get("url", vision.OLLAMA_URL),
        )
        if model not in {item["id"] for item in catalog[provider]}:
            raise HTTPException(status_code=400, detail="モデルを選び直してください")
        api_key = request_api_key.strip()
        if len(api_key) > 512:
            raise HTTPException(status_code=400, detail="APIキーを確認してください")
    else:
        model = settings["models"][provider]
        api_key = settings["api_keys"].get(provider, "")
    if provider != "local" and not api_key:
        raise HTTPException(status_code=400, detail="設定画面でAPIキーを登録してください")
    uploads = [*files, *([file] if file else [])]
    if not uploads or len(uploads) > 3:
        raise HTTPException(status_code=400, detail="写真は1〜3枚選んでください")
    if any(upload.content_type and not upload.content_type.startswith("image/") for upload in uploads):
        raise HTTPException(status_code=415, detail="画像ファイルを選んでください")
    raw_images = [await upload.read(vision.MAX_UPLOAD_BYTES + 1) for upload in uploads]
    try:
        photo_metadata: dict[str, object] = {}
        for raw in raw_images:
            candidate_metadata = await run_in_threadpool(vision.extract_exif_context, raw)
            for key, value in candidate_metadata.items():
                photo_metadata.setdefault(key, value)
        prepared = [await run_in_threadpool(vision.prepare_image, raw) for raw in raw_images]
        context = {
            "location": location or str(photo_metadata.get("location", "")),
            "observed_date": observed_date or str(photo_metadata.get("observed_date", "")),
            "size": size,
        }
        if provider == "openai":
            result = await run_in_threadpool(vision.identify_openai, prepared, api_key, model, **context)
        elif provider == "anthropic":
            result = await run_in_threadpool(vision.identify_anthropic, prepared, api_key, model, **context)
        elif provider == "gemini":
            result = await run_in_threadpool(vision.identify_gemini, prepared, api_key, model, **context)
        else:
            result = await run_in_threadpool(
                vision.identify, prepared, model,
                ollama_url=(settings.get("local_llm") or {}).get("url", vision.OLLAMA_URL),
                **context
            )
        if use_plantnet:
            plantnet_key = request_plantnet_key.strip() if PUBLIC_MODE else settings["api_keys"].get("plantnet", "")
            if not plantnet_key:
                result["plantnet_status"] = "not_configured"
            elif result.get("category") != "植物":
                result["plantnet_status"] = "not_plant"
            else:
                try:
                    specialist = await run_in_threadpool(
                        vision.identify_plantnet, prepared, plantnet_key
                    )
                    result = vision.merge_plant_results(result, specialist)
                except vision.VisionError as plantnet_error:
                    result["plantnet_status"] = "unavailable"
                    result["plantnet_message"] = str(plantnet_error)
        result = await run_in_threadpool(vision.apply_evidence_gate, result)
        result["photo_metadata"] = photo_metadata
    except vision.VisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(result)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8523)
