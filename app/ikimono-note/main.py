"""ikimono-note: photograph-based local species identification.

同じアプリを2つの役割で動かす。8523 は運営者用 (非公開モード・設定の保存が可能)、
8524 は公開版 (BYOK・設定は読み取り専用) で Tailscale Funnel の向け先。
設定ファイルは共有するため、運営者用での変更は公開版にも反映される。
"""

import asyncio
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
import jobs
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
# 識別を後ろで走らせるか。サーバーレスの置き場ではレスポンスを返した瞬間に CPU を
# 止められるため (Cloud Run / Container Apps の既定)、後ろの仕事はそこで凍る。
# 0 を渡すと同期で返す。画面はどちらでも動く (札が返らなければ結果そのものとして扱う)。
BACKGROUND_JOBS = os.getenv("IKIMONO_BACKGROUND_JOBS", "1").lower() not in {"0", "false", "no"}
# Google Drive 連携のクライアントID。公開情報なので画面へ渡してよい (秘密鍵は使わない)
GOOGLE_CLIENT_ID = os.getenv("IKIMONO_GOOGLE_CLIENT_ID", "").strip()
ALLOWED_HOSTS = [host.strip() for host in os.getenv("IKIMONO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
# 運営者用 (非公開モード) こそ設定を書き換えられるので、Host の検証は両モードで効かせる。
# 以前は公開モードだけに付けていたため、運営者用が素通しだった。
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# Cloud Run は同じサービスを2つのURLで配信する (新形式と旧形式)。両方通しておかないと
# 片方が 400 になるが、通すだけだとログインが壊れる。始めるときの state を載せた
# cookie はドメインごとなので、旧形式で始めて新形式へ返ってくると cookie が届かず、
# 「ログインできませんでした」になる。返り先は PUBLIC_ORIGIN 固定なので、入口の側を
# そこへ寄せる。
CANONICAL_HOST = auth.PUBLIC_ORIGIN.split("://", 1)[-1].rstrip("/") if auth.PUBLIC_ORIGIN else ""

# 手元から直接あてる入口は寄せない。運営者用も公開版も PUBLIC_ORIGIN を同じ
# ~/.env から読むので、これが無いと 192.168.11.9:8523 の運営者用画面が公開サイトへ
# 飛ぶ。ログインの流れが2つのドメインをまたぐのは公開の入口だけの問題で、
# 手元からの接続はそもそも Google を経由しない。
def _is_local_entry(host: str) -> bool:
    name = host.rsplit(":", 1)[0].strip("[]")
    return (name in {"localhost", "127.0.0.1", "::1", "ubuntu-server-app"}
            or name.startswith(("192.168.", "10.", "100.")))


@app.middleware("http")
async def keep_one_origin(request: Request, call_next):
    host = request.headers.get("host", "")
    if (PUBLIC_MODE and CANONICAL_HOST and host and host != CANONICAL_HOST
            and host in ALLOWED_HOSTS and not _is_local_entry(host)):
        target = auth.PUBLIC_ORIGIN.rstrip("/") + request.url.path
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(target, status_code=307)
    return await call_next(request)
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_RATE_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    """利用者のIP。公開版は前段のプロキシ越しに来る。

    公開版は 127.0.0.1 で待ち受け、前段 (Tailscale Funnel / Cloud Run など) だけが
    つながる。そのため request.client.host は常に前段のアドレスで、**全員が同じIPに
    見える**。この状態でIPごとの制限をかけると、1分6回も1日N回も「全利用者の合計」に
    なり、最初の1人が使い切ると他の全員が閉め出される。

    運営者用では読まない。あちらは 0.0.0.0 で待ち受けるので、ヘッダを名乗るだけで
    別人になれてしまう (もっとも運営者用に回数制限は掛けていない)。
    """
    if PUBLIC_MODE:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:64]
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request, scope: str, limit: int, window: int = 60) -> None:
    client = _client_ip(request)
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
              "/favicon.svg", "/theme.js", "/health",
              # クローラと、共有したときの見え方。ログインへ飛ばすと robots.txt が
              # 読めず、共有カードの画像も出ない
              "/robots.txt", "/sitemap.xml", "/ogp.png"}
OPEN_PREFIXES = ("/assets/", "/vendor/", "/static/")

# 見知らぬ人が、その場で1回試せるようにするための枠。
#
# 公開版は BYOK で、利用者が自分のAPIキーを入れないと1枚も調べられない。ログインを
# 外しても、入り口の次に「APIキーを入れてください」が立っているだけで、通りすがりの
# 人には何も起きない。試させるには運営者の枠を分けるしかない。
#
# 既定は 0 (無効)。有効にすると運営者の Gemini の枠を見知らぬ人が使うので、
# 入れるかどうかは運営者が決めること。
TRIAL_PER_DAY = max(0, int(os.getenv("IKIMONO_PUBLIC_TRIAL_PER_DAY", "0") or 0))
TRIAL_MODEL = os.getenv("IKIMONO_PUBLIC_TRIAL_MODEL", "gemini-3.5-flash-lite")


_TRIAL_LOCK = threading.Lock()
_TRIAL_USED: dict[tuple[str, str], int] = {}


def _trial_take(request: Request) -> bool:
    """お試しを1回ぶん使う。使い切っていれば False。

    日付ごとに数えるだけの素朴な作り。プロセスが再起動すれば戻るが、無料枠の
    使いすぎを緩く抑えるのが目的で、厳密な会計ではない。
    """
    client = _client_ip(request)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _TRIAL_LOCK:
        for key in [k for k in _TRIAL_USED if k[1] != today]:
            _TRIAL_USED.pop(key, None)
        used = _TRIAL_USED.get((client, today), 0)
        if used >= TRIAL_PER_DAY:
            return False
        _TRIAL_USED[(client, today)] = used + 1
        return True


def trial_enabled() -> bool:
    """お試し枠が使える状態か。運営者のキーが無ければ、数を入れても意味がない。"""
    if not (PUBLIC_MODE and TRIAL_PER_DAY):
        return False
    return bool(config_store.load()["api_keys"].get("gemini"))


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
    # お試し枠があるなら、撮影画面と識別はログイン前でも通す。ここを閉じたままだと
    # 枠を用意しても誰も辿り着けない (記録・設定はログインの内側のまま)
    # 札の問い合わせ先 (/identify/job/<id>) も開ける。ここを閉じたままだと、識別は
    # 始まるのに結果を取りに行けず、ポーリングがログイン画面のHTMLを受け取って
    # 「Unexpected token '<'」で終わる (実測でそうなった)
    # 設定も開ける。お試しを使い切った人に「設定でご自身のAPIキーを」と案内しながら
    # その設定がログインの内側だと、案内が行き止まりになる。公開版の設定は
    # ブラウザの中だけに書く (POST /api/settings は公開版では403) ので、開けても安全
    if trial_enabled() and (path in {"/", "/settings", "/identify",
                                     "/api/settings", "/api/photo-metadata"}
                            or path.startswith("/identify/job/")):
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
    # state が合わなければ、この画面を開かせたのは本人ではない。
    # どれで落ちたかは残す。理由が出ないと、本番の「ログインできませんでした」から
    # 先へ進めない (実際に切り分けできず止まった)。値そのものは出さない。
    if not flow:
        print("login failed: 始めたときの cookie が届いていない", flush=True)
        return RedirectResponse("/login?failed=1", status_code=303)
    if not state or not secrets.compare_digest(flow.get("state", ""), state):
        print("login failed: state が一致しない", flush=True)
        return RedirectResponse("/login?failed=1", status_code=303)
    try:
        user = await_free(auth.finish_login, code, flow["verifier"], flow["nonce"])
    except auth.AuthError as exc:
        print(f"login failed: {exc}", flush=True)
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


@app.get("/robots.txt", include_in_schema=False)
def robots() -> FileResponse:
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> FileResponse:
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


@app.get("/ogp.png", include_in_schema=False)
def ogp() -> FileResponse:
    return FileResponse(STATIC_DIR / "ogp.png", media_type="image/png")


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
    # お試し枠で走るモデルは、利用者が選んだものではなくこちらが決める。
    # 画面が別の名前を出したままだと、どのAIに写真が行くのかを偽ることになる
    if trial_enabled():
        result["trial"] = {"per_day": TRIAL_PER_DAY, "provider": "gemini", "model": TRIAL_MODEL}
    result["google_client_id"] = GOOGLE_CLIENT_ID
    # 商品APIの状態は運営者だけのもの。公開版の訪問者に運営者のアソシエイト口座の
    # 事情を渡さない (広告を有効にした公開版でも affiliate 一式は返るため、
    # public() 側には最初から入れず、ここで足す)
    if not PUBLIC_MODE:
        result["creators_api_state"] = config_store.load().get("creators_api_state") or {}
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


# Amazon の適格審査は日単位でしか変わらない (直近30日の適格販売が要る)。断られる
# たびに呼び直しても答えは同じで、識別1回につき往復ぶんの待ち時間と、失敗のログ
# だけが積まれる。本番のエラーログは実際これで埋まり、ほかの異変が埋もれていた。
# 断られたらしばらく呼ばない。1時間なら、資格が戻ったときも同じ日のうちに拾える。
_CREATORS_PAUSE_SECONDS = 3600
_creators_pause_until = 0.0

# 同じ切り口で何度も Amazon を叩かない。
#
# 画面を開くたびに並びを変えたいが、そのたびに問い合わせるのは筋が悪い。商品API
# には秒あたりの上限があり、そこは売上に応じてしか増えない。多めに取って覚えて
# おき、どれを見せるかはブラウザ側で選ぶ。問い合わせは減り、並びは毎回変わる。
#
# 覚えるのは題名・URL・画像だけで、価格と在庫は持たない。アソシエイトの規約は
# 価格情報の保持を24時間までに制限しているが、そもそも持っていない。それでも
# 品揃えは動くので、6時間で捨てる。
_PRODUCT_TTL_SECONDS = 6 * 3600
_PRODUCT_CACHE_MAX = 200
_product_cache: dict[tuple[str, str], tuple[float, list[dict[str, str]]]] = {}
_PRODUCT_CACHE_LOCK = threading.Lock()


def _products_cached(key: tuple[str, str]) -> list[dict[str, str]] | None:
    with _PRODUCT_CACHE_LOCK:
        found = _product_cache.get(key)
        if not found:
            return None
        stored_at, products = found
        if time.monotonic() - stored_at > _PRODUCT_TTL_SECONDS:
            _product_cache.pop(key, None)
            return None
        return products


def _remember_products(key: tuple[str, str], products: list[dict[str, str]]) -> None:
    with _PRODUCT_CACHE_LOCK:
        if len(_product_cache) >= _PRODUCT_CACHE_MAX:
            # 古い順に捨てる。件数が知れているので、並べ替えて足りる
            oldest = sorted(_product_cache.items(), key=lambda item: item[1][0])
            for stale, _ in oldest[: len(oldest) // 2 or 1]:
                _product_cache.pop(stale, None)
        _product_cache[key] = (time.monotonic(), products)


def _creators_paused() -> bool:
    return time.monotonic() < _creators_pause_until


def _pause_creators(reason: str) -> None:
    """設定の誤りと資格切れは、待っても次の1回で直らない。混雑 (429) も同じ。"""
    global _creators_pause_until
    _creators_pause_until = time.monotonic() + _CREATORS_PAUSE_SECONDS
    print(f"Amazon商品APIを{_CREATORS_PAUSE_SECONDS // 60}分ほど呼びません（{reason}）", flush=True)


@app.get("/api/amazon/products")
async def amazon_products(q: str = "", index: str = "All") -> JSONResponse:
    if PUBLIC_MODE and not PUBLIC_AFFILIATE_ENABLED:
        raise HTTPException(status_code=404, detail="公開ベータ版では広告を表示しません")
    settings = config_store.load()
    affiliate = settings["affiliate"]
    keys = settings["api_keys"]
    if not affiliate.get("product_enabled"):
        raise HTTPException(status_code=404, detail="商品APIが設定されていません")
    cache_key = (" ".join(str(q).split())[:80], str(index))
    cached = _products_cached(cache_key)
    if cached is not None:
        return JSONResponse({"products": cached})
    if _creators_paused():
        # 404 は「出すものが無い」。画面はカードを描かずに済ませる (503 は赤字になる)
        raise HTTPException(status_code=404, detail="商品APIはいま使えません")
    try:
        # 10件は商品APIの上限。見せるのは4件でも、多めに貰っておけば、次に開いた
        # ときの並びを問い合わせ無しで変えられる
        products = await run_in_threadpool(creators_api.search_products, q, keys.get("amazon_creators_id", ""), keys.get("amazon_creators_secret", ""), affiliate.get("partner_tag", ""), 10, index)
    except creators_api.CreatorsAPIError as exc:
        # 断られたことを設定画面へ届ける。journal だけだと、運営者は「登録済み」の
        # 表示を見て設定が効いていると思い込む
        config_store.record_creators_result(False, reason=exc.reason, hint=exc.hint, status=exc.status)
        if exc.status in (401, 403, 429):
            _pause_creators(exc.reason or exc.status)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    config_store.record_creators_result(True)
    _remember_products(cache_key, products)
    if not products:
        raise HTTPException(status_code=404, detail="関連商品が見つかりません")
    return JSONResponse({"products": products})


# 利用者のクラウドストレージへの中継。認証情報は毎回受け取り、保存も記録もしない。


@app.get("/health")
def health() -> dict[str, object]:
    """生きているかどうか。

    ログインの内側に置いていたため、外からは 303 が返るだけで、死活の監視を
    掛けようがなかった。OPEN_PATHS に "/healthz" とだけ書いてあったが、その名前の
    ルートは無く 404 で、どちらからも確かめられない状態だった。

    公開版では中身を伏せる。動いているかを知るのに、運営者が選んだモデルの名前は
    要らない。
    """
    if PUBLIC_MODE:
        return {"ok": True}
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


_RUNNING_TASKS: set[asyncio.Task] = set()


def _job_owner(request: Request) -> str:
    """公開版では、札を知っていても他人の結果は見えないようにする。"""
    if not PUBLIC_MODE:
        return ""
    session = auth.read_session(request.cookies.get(auth.SESSION_COOKIE))
    return str((session or {}).get("sub") or "")


@app.get("/identify/job/{job_id}")
def identify_job(request: Request, job_id: str) -> JSONResponse:
    """走らせた識別の様子を返す。画面を更新したあとはここへ聞きに来る。"""
    job = jobs.get(job_id, _job_owner(request))
    if job is None:
        # 期限切れ・再起動・別人。どれでも利用者にできることは同じ
        raise HTTPException(status_code=404, detail="この調べものは見つかりませんでした。もう一度お試しください。")
    if job["status"] == "running":
        return JSONResponse({"status": "running"})
    if job["status"] == "error":
        return JSONResponse({"status": "error", "status_code": job["status_code"],
                             "detail": job["detail"]})
    return JSONResponse({"status": "done", "result": job["result"]})


@app.post("/identify")
async def identify(
    request: Request,
    background: bool = Form(default=False),
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
        # 自分のキーが無い人には、運営者の枠から1日 TRIAL_PER_DAY 回だけ貸す。
        # ここが無いと、通りすがりの人は入り口の次で必ず止まる
        if not api_key and trial_enabled():
            if not _trial_take(request):
                raise HTTPException(status_code=429, detail=(
                    "今日のお試しは終わりです。設定画面でご自身のAPIキーを登録すると、"
                    "続けて調べられます。"))
            provider = "gemini"
            model = TRIAL_MODEL
            api_key = settings["api_keys"].get("gemini", "")
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
    work = dict(
        provider=provider, model=model, api_key=api_key, settings=settings,
        location=location, observed_date=observed_date, size=size,
        use_plantnet=use_plantnet, request_plantnet_key=request_plantnet_key)
    if background and BACKGROUND_JOBS:
        # 写真はこのあとの仕事の中にしか残らない。終わったら捨てる (jobs.py)
        job_id = jobs.start(_job_owner(request))
        # 参照を持たないと、走っている途中で回収されることがある
        task = asyncio.create_task(_run_identify_job(job_id, raw_images, work))
        _RUNNING_TASKS.add(task)
        task.add_done_callback(_RUNNING_TASKS.discard)
        return JSONResponse({"status": "running", "job": job_id}, status_code=202)
    return JSONResponse(await _identify_images(
        raw_images, provider=provider, model=model, api_key=api_key, settings=settings,
        location=location, observed_date=observed_date, size=size,
        use_plantnet=use_plantnet, request_plantnet_key=request_plantnet_key))


async def _identify_images(
    raw_images: list[bytes], *, provider: str, model: str, api_key: str,
    settings: dict, location: str, observed_date: str, size: str,
    use_plantnet: bool, request_plantnet_key: str,
) -> dict:
    """写真の生バイトから結果を作る。HTTP 層と、後ろで走らせる仕事の共通部分。

    切り出したのは、画面を更新しても識別を続けられるようにするため。同じ手順を
    2か所に書くと、質のゲートや EXIF の扱いが片方だけ古くなる。
    """
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
    return result


async def _run_identify_job(job_id: str, raw_images: list[bytes], work: dict) -> None:
    """後ろで走らせるぶん。例外は札の側へ移し、ここでは外に投げない。"""
    try:
        jobs.finish(job_id, await _identify_images(raw_images, **work))
    except HTTPException as exc:
        jobs.fail(job_id, exc.status_code, exc.detail)
    except Exception as exc:  # noqa: BLE001 - 何であれ札に残さないと画面が待ち続ける
        print(f"[ikimono-note] 識別 {job_id} が落ちました: {exc!r}", flush=True)
        jobs.fail(job_id, 500, "調べられませんでした。もう一度お試しください。")
    finally:
        raw_images.clear()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8523)
