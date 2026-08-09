"""species-explorer: photograph-based local species identification (port 8523)."""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

import config_store
import vision

class SettingsUpdate(BaseModel):
    provider: str
    models: dict[str, str] = Field(default_factory=dict)
    api_keys: dict[str, str | None] = Field(default_factory=dict)
    delete_keys: list[str] = Field(default_factory=list)


app = FastAPI(title="Species Explorer")
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings", include_in_schema=False)
def settings() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/settings")
def get_settings() -> dict[str, object]:
    return config_store.public()


@app.post("/api/settings")
def save_settings(update: SettingsUpdate) -> dict[str, object]:
    try:
        return config_store.save(
            provider=update.provider,
            models=update.models,
            api_keys=update.api_keys,
            delete_keys=update.delete_keys,
        )
    except config_store.SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "model": vision.MODEL, "local_processing": True, "providers": ["local", "openai", "anthropic"]}


@app.post("/identify")
async def identify(file: UploadFile = File(...)) -> JSONResponse:
    settings = config_store.load()
    provider = settings["provider"]
    model = settings["models"][provider]
    api_key = settings["api_keys"].get(provider, "")
    if provider != "local" and not api_key:
        raise HTTPException(status_code=400, detail="設定画面でAPIキーを登録してください")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="画像ファイルを選んでください")
    raw = await file.read(vision.MAX_UPLOAD_BYTES + 1)
    try:
        prepared = await run_in_threadpool(vision.prepare_image, raw)
        if provider == "openai":
            result = await run_in_threadpool(vision.identify_openai, prepared, api_key, model)
        elif provider == "anthropic":
            result = await run_in_threadpool(vision.identify_anthropic, prepared, api_key, model)
        else:
            result = await run_in_threadpool(vision.identify, prepared, model)
    except vision.VisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(result)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8523)
