"""Local-only HTTP compatibility experiment; no credentials or app imports."""
import httpx
import threading
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from workers import asgi

app = FastAPI()
TARGET = "https://example.com/"


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/probe/{mode}")
async def probe(mode: str):
    if mode not in {"sync", "async"}:
        return {"ok": False, "error": "unknown mode"}
    try:
        if mode == "sync":
            with httpx.Client(timeout=10) as client:
                response = client.get(TARGET)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(TARGET)
        return {"ok": response.status_code == 200, "status": response.status_code,
                "example_domain": "Example Domain" in response.text}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


@app.get("/sync-health")
def sync_health():
    return {"ok": True}


@app.get("/threadpool")
async def threadpool():
    try:
        result = await run_in_threadpool(lambda: "completed")
        return {"ok": result == "completed"}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


@app.get("/native-thread")
async def native_thread():
    try:
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


@app.get("/post/{kind}")
async def post(kind: str):
    if kind not in {"json", "form", "multipart"}:
        return {"ok": False, "error": "unknown kind"}
    payloads = {
        "json": {"json": {"probe": "synthetic"}},
        "form": {"data": {"probe": "synthetic"}},
        "multipart": {"data": {"probe": "synthetic"},
                      "files": {"images": ("probe.jpg", b"synthetic-photo", "image/jpeg")}},
    }
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post("http://127.0.0.1:8789/", **payloads[kind])
        response.raise_for_status()
        body = response.json()
        return {"ok": "synthetic" in body["body"], **body}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


Default = asgi.entrypoint(app)
