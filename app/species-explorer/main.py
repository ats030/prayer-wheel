"""species-explorer: photograph-based local species identification (port 8523)."""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

import vision

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


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "model": vision.MODEL, "local_processing": True, "providers": ["local", "openai", "anthropic"]}


@app.post("/identify")
async def identify(
    file: UploadFile = File(...),
    provider: str = Form("local"),
    api_key: str | None = Form(None),
) -> JSONResponse:
    if provider not in {"local", "openai", "anthropic"}:
        raise HTTPException(status_code=400, detail="計算資源を選び直してください")
    if provider != "local" and not (api_key or "").strip():
        raise HTTPException(status_code=400, detail="APIキーを入力してください")
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="画像ファイルを選んでください")
    raw = await file.read(vision.MAX_UPLOAD_BYTES + 1)
    try:
        prepared = await run_in_threadpool(vision.prepare_image, raw)
        if provider == "openai":
            result = await run_in_threadpool(vision.identify_openai, prepared, api_key.strip())
        elif provider == "anthropic":
            result = await run_in_threadpool(vision.identify_anthropic, prepared, api_key.strip())
        else:
            result = await run_in_threadpool(vision.identify, prepared)
    except vision.VisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(result)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8523)
