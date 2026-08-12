"""ikimono-note: photograph-based local species identification.

同じアプリを2つの役割で動かす。8523 は運営者用 (非公開モード・設定の保存が可能)、
8524 は公開版 (BYOK・設定は読み取り専用) で Tailscale Funnel の向け先。
設定ファイルは共有するため、運営者用での変更は公開版にも反映される。
"""

from collections import defaultdict, deque
from pathlib import Path
import os
import threading
import time

import secrets

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

import auth
import config_store
import image_quality
import creators_api
import pipeline
import vision

class SettingsUpdate(BaseModel):
    provider: str
    models: dict[str, str] = Field(default_factory=dict)
    local_llm: dict[str, object] | None = None
    api_keys: dict[str, str | None] = Field(default_factory=dict)
    delete_keys: list[str] = Field(default_factory=list)
    affiliate: dict[str, object] = Field(default_factory=dict)


PUBLIC_MODE = os.getenv("IKIMONO_PUBLIC_MODE", "").lower() in {"1", "true", "yes"}
# 一般公開では API ドキュメントを閉じる。Swagger UI は CDN から読み込むため CSP に
# 阻まれて白紙になるうえ、公開の入口に晒す必要がない
app = FastAPI(
    title="生きものノート",
    docs_url=None if PUBLIC_MODE else "/docs",
    redoc_url=None if PUBLIC_MODE else "/redoc",
    openapi_url=None if PUBLIC_MODE else "/openapi.json",
)
STATIC_DIR = Path(__file__).parent / "static"
PUBLIC_LOCAL_ENABLED = os.getenv("IKIMONO_PUBLIC_LOCAL", "").lower() in {"1", "true", "yes"}
PUBLIC_AFFILIATE_ENABLED = os.getenv("IKIMONO_PUBLIC_AFFILIATE", "").lower() in {"1", "true", "yes"}
# Google Drive 連携のクライアントID。公開情報なので画面へ渡してよい (秘密鍵は使わない)
GOOGLE_CLIENT_ID = os.getenv("IKIMONO_GOOGLE_CLIENT_ID", "").strip()
ALLOWED_HOSTS = [host.strip() for host in os.getenv("IKIMONO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
# 運営者用 (非公開モード) こそ設定を書き換えられるので、Host の検証は両モードで効かせる。
# 以前は公開モードだけに付けていたため、運営者用が素通しだった。
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


# 'unsafe-inline' を置かずに済むよう、CSS/JS はすべて /assets と /theme.js から配る。
# 外部を許すのは、利用者が押して初めて出る地図タイルと、広告の商品画像だけ。
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-src https://accounts.google.com",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "script-src 'self' https://accounts.google.com",
    "style-src 'self'",
    "connect-src 'self' https://accounts.google.com https://oauth2.googleapis.com https://www.googleapis.com",
    "img-src 'self' blob: data: https://tile.openstreetmap.org https://cyberjapandata.gsi.go.jp https://*.media-amazon.com https://*.ssl-images-amazon.com",
])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self)"
    # same-origin にすると、開いたポップアップとの window.opener が切れる。
    # Google の認可はポップアップで許可を取り、親へ postMessage で結果を返すので、
    # 認可が通っているのに結果が届かず「ポップアップが閉じられた」ようにしか見えない。
    # allow-popups は、自分が開いたポップアップとのやり取りだけを許す。
    # 別サイトから開かれたときにこちらを覗かれない保護は残る。
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    # Cache-Control が無いと、ブラウザは Last-Modified から新鮮期間を推測して
    # 再検証せずに古い CSS/JS を使い続ける。HTML が古いと、新しく足したスクリプトの
    # <script> タグごと存在しないことになり、変更がまるごと反映されない。
    # ETag は付いているので no-cache でも 304 で済む。
    if request.url.path.startswith("/vendor/"):
        # 同梱ライブラリはバージョン固定で中身が変わらない
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _page(name: str) -> HTMLResponse:
    """モードを body に埋めて返す。

    運営者用と公開版は同じHTMLを使い、差は data-only 属性で宣言する。JS で後から
    書き換えると、どこが違うのかコードを追わないと分からず、確定するまで一瞬
    反対側が見える。サーバーが最初から決めておけばその両方が起きない。
    """
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
    mode = "public" if PUBLIC_MODE else "operator"
    # 公開版で Ollama を出すかは PUBLIC_LOCAL の設定次第。モードとは別の軸
    show_local = "0" if (PUBLIC_MODE and not PUBLIC_LOCAL_ENABLED) else "1"
    html = html.replace("<body", f'<body data-app-mode="{mode}" data-show-local="{show_local}"', 1)
    return HTMLResponse(html)


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return _page("index.html")


@app.get("/settings", include_in_schema=False)
def settings() -> HTMLResponse:
    return _page("settings.html")


@app.get("/history", include_in_schema=False)
def history() -> HTMLResponse:
    return _page("history.html")


@app.get("/privacy", include_in_schema=False)
def privacy() -> HTMLResponse:
    return _page("privacy.html")


@app.get("/terms", include_in_schema=False)
def terms() -> HTMLResponse:
    return _page("terms.html")


# ── ログイン ────────────────────────────────────────────
# 公開版では必須。サーバーが持つのは識別子とメールアドレスだけで、写真も記録も
# 設定もAPIキーも利用者の側に残る。ログインしても預かるものは増えない。

LOGIN_FLOW_COOKIE = "ikimono_login"

# ログインしていなくても通す道。ログイン自体と、読んでから決めるための文書、
# それに画面を組み立てる部品。ここを絞りすぎるとログイン画面が裸になる。
OPEN_PATHS = {"/login", "/auth/google", "/auth/callback", "/api/me", "/privacy", "/terms",
              "/favicon.svg", "/theme.js", "/healthz"}
OPEN_PREFIXES = ("/assets/", "/vendor/", "/static/")


@app.middleware("http")
async def require_login(request: Request, call_next):
    """公開版では、ログインしていない人を入口へ戻す。

    ログインが設定されていないときは通す。設定を入れる前に必須にすると、運営者を
    含めて誰も入れないアプリになる。運営者用 (8523) は tailnet の中だけなので、
    ここでは求めない。二重にすると、設定の不備で自分が締め出される。
    """
    path = request.url.path
    if (not PUBLIC_MODE or not auth.configured()
            or path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)):
        return await call_next(request)
    if auth.read_session(request.cookies.get(auth.SESSION_COOKIE)):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "ログインしてください"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def await_free(function, *args):
    """同期のまま呼ぶ。ここは待ち時間が短く、別スレッドへ逃がす利点がない。"""
    return function(*args)


@app.get("/login", include_in_schema=False)
def login_page() -> HTMLResponse:
    return _page("login.html")


@app.get("/auth/google", include_in_schema=False)
def auth_google(request: Request) -> RedirectResponse:
    if not auth.configured():
        raise HTTPException(status_code=503, detail="ログインはまだ使えません")
    _rate_limit(request, "login", 10)
    url, flow = auth.start_login()
    response = RedirectResponse(url, status_code=303)
    # 始めた本人だけが終えられるようにする。署名付きで、10分で切れる
    response.set_cookie(LOGIN_FLOW_COOKIE, auth.sign_session({**flow, "exp": int(time.time()) + 600}),
                        max_age=600, httponly=True, secure=True, samesite="lax", path="/auth")
    return response


@app.get("/auth/callback", include_in_schema=False)
def auth_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    if error or not code:
        return RedirectResponse("/login?failed=1", status_code=303)
    flow = auth.read_session(request.cookies.get(LOGIN_FLOW_COOKIE))
    # state が合わなければ、この画面を開かせたのは本人ではない
    if not flow or not state or not secrets.compare_digest(flow.get("state", ""), state):
        return RedirectResponse("/login?failed=1", status_code=303)
    try:
        user = await_free(auth.finish_login, code, flow["verifier"], flow["nonce"])
    except auth.AuthError:
        return RedirectResponse("/login?failed=1", status_code=303)
    response = RedirectResponse("/settings", status_code=303)
    response.set_cookie(auth.SESSION_COOKIE, auth.session_for(user),
                        max_age=auth.SESSION_DAYS * 86400, httponly=True, secure=True, samesite="lax", path="/")
    response.delete_cookie(LOGIN_FLOW_COOKIE, path="/auth")
    return response


@app.post("/auth/logout", include_in_schema=False)
def auth_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@app.get("/api/me")
def api_me(request: Request) -> JSONResponse:
    """ログイン状態。使えるかどうかも合わせて返し、画面が理由を出せるようにする。"""
    session = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    return JSONResponse({
        "available": auth.configured(),
        "reason": auth.unavailable_reason(),
        "signed_in": bool(session),
        "email": session.get("email") if session else None,
    })


@app.post("/api/me/delete")
def api_me_delete(request: Request) -> JSONResponse:
    """退会。持っているものが少ないので、消すのも一度で終わる。"""
    session = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    if not session:
        raise HTTPException(status_code=401, detail="ログインしていません")
    auth.delete_user(session["sub"])
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/theme.js", include_in_schema=False)
def theme_script() -> FileResponse:
    return FileResponse(STATIC_DIR / "theme.js", media_type="text/javascript")


# Leaflet は同梱して配信する。CDN から読むと、地図を見た利用者のIPが第三者へ渡り、
# プライバシーポリシーの送信先一覧と実態がずれる (BSD-2-Clause, vendor/leaflet/LICENSE)
app.mount("/vendor", StaticFiles(directory=STATIC_DIR / "vendor"), name="vendor")
# ページのCSS/JSは外部ファイルに置く。インラインのままだと CSP に 'unsafe-inline' が
# 必要になり、BYOKでブラウザにAPIキーを預けるこのアプリでは守りとして弱すぎる
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/api/settings")
def get_settings() -> dict[str, object]:
    result = config_store.public()
    result["public_mode"] = PUBLIC_MODE
    result["google_client_id"] = GOOGLE_CLIENT_ID
    if PUBLIC_MODE:
        result["local_llm"] = {"url": ""}
        result["api_key_configured"] = {
            provider: False for provider in ("openai", "anthropic", "gemini", "plantnet")
        }
        if not PUBLIC_AFFILIATE_ENABLED:
            result["affiliate"] = {
                "title": "", "url": "", "enabled": False,
                "metrics": {"impressions": 0, "clicks": 0},
                "partner_tag": "", "product_enabled": False,
                "creators_api_configured": False,
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
    if PUBLIC_MODE and not PUBLIC_AFFILIATE_ENABLED:
        raise HTTPException(status_code=404, detail="公開ベータ版では広告を表示しません")
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
    if PUBLIC_MODE and not PUBLIC_AFFILIATE_ENABLED:
        raise HTTPException(status_code=404, detail="公開ベータ版では広告を表示しません")
    try:
        target = config_store.affiliate_target(q)
        config_store.record_affiliate("clicks")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(target, status_code=302)


@app.post("/api/affiliate/click")
def affiliate_click_event() -> dict[str, bool]:
    if PUBLIC_MODE and not PUBLIC_AFFILIATE_ENABLED:
        raise HTTPException(status_code=404, detail="公開ベータ版では広告を表示しません")
    if not config_store.load()["affiliate"]["enabled"]:
        raise HTTPException(status_code=404, detail="広告が設定されていません")
    config_store.record_affiliate("clicks")
    return {"ok": True}


@app.get("/api/amazon/products")
async def amazon_products(q: str = "", index: str = "All") -> JSONResponse:
    if PUBLIC_MODE and not PUBLIC_AFFILIATE_ENABLED:
        raise HTTPException(status_code=404, detail="公開ベータ版では広告を表示しません")
    settings = config_store.load()
    affiliate = settings["affiliate"]
    keys = settings["api_keys"]
    if not affiliate.get("product_enabled"):
        raise HTTPException(status_code=404, detail="商品APIが設定されていません")
    try:
        products = await run_in_threadpool(creators_api.search_products, q, keys.get("amazon_creators_id", ""), keys.get("amazon_creators_secret", ""), affiliate.get("partner_tag", ""), 4, index)
    except creators_api.CreatorsAPIError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not products:
        raise HTTPException(status_code=404, detail="関連商品が見つかりません")
    return JSONResponse({"products": products})


# 利用者のクラウドストレージへの中継。認証情報は毎回受け取り、保存も記録もしない。


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
            raise HTTPException(status_code=415, detail="写真を選んでください")
        raw = await upload.read(vision.MAX_UPLOAD_BYTES + 1)
        if len(raw) > vision.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="写真は1枚15MB以下にしてください")
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
        raise HTTPException(status_code=400, detail="使うAIを選び直してください")
    if PUBLIC_MODE and provider == "local" and not PUBLIC_LOCAL_ENABLED:
        raise HTTPException(status_code=403, detail="公開版ではOllamaを使えません")
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
        raise HTTPException(status_code=415, detail="写真を選んでください")
    raw_images = [await upload.read(vision.MAX_UPLOAD_BYTES + 1) for upload in uploads]
    try:
        photo_metadata: dict[str, object] = {}
        for raw in raw_images:
            candidate_metadata = await run_in_threadpool(vision.extract_exif_context, raw)
            for key, value in candidate_metadata.items():
                photo_metadata.setdefault(key, value)
        # 質を見てから送る。暗すぎる・小さすぎる写真をAIへ送っても、返るのは
        # 自信のない推測かもっともらしい誤りで、利用者の枠を使うだけになる。
        quality = [await run_in_threadpool(image_quality.judge, raw) for raw in raw_images]
        unusable = [q for q in quality if not q["ok"]]
        if unusable:
            raise HTTPException(status_code=422, detail={
                "message": "この写真では調べられません。",
                "problems": [p for q in unusable for p in q["problems"] if p["level"] == image_quality.BLOCK],
            })

        prepared = [await run_in_threadpool(vision.prepare_image, raw) for raw in raw_images]
        context = {
            "location": location or str(photo_metadata.get("location", "")),
            "observed_date": observed_date or str(photo_metadata.get("observed_date", "")),
            "size": size,
        }
        plantnet_key = (request_plantnet_key.strip() if PUBLIC_MODE else settings["api_keys"].get("plantnet", "")) if use_plantnet else ""
        result = await run_in_threadpool(
            pipeline.identify_all, prepared,
            provider=provider, model=model, api_key=api_key,
            ollama_url=(settings.get("local_llm") or {}).get("url", vision.OLLAMA_URL),
            use_plantnet=use_plantnet, plantnet_key=plantnet_key,
            **context,
        )
        result["photo_metadata"] = photo_metadata
        # 弾くほどではない注意は、結果と一緒に返す。次に撮るときの助けになる
        result["photo_notes"] = [problem for q in quality for problem in q["problems"]]
    except vision.VisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(result)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8523)
