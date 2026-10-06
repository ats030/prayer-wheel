"""exam-trainer: FastAPI routes (port 8522).

Screens follow the arrangement settled in the writing editor: the toolbar acts
on the document (here: the exam), and each tab owns both the control that runs
something and the result it produces.
"""

from __future__ import annotations

import logging
import re
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Literal
from pydantic import BaseModel

from . import bank, db, jobs, kouko, products, ollama_client, web
from .config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A job that was mid-run when the service stopped would otherwise sit at
    # "running" with nothing running it.
    jobs.recover_running()
    jobs.start_worker()
    yield


app = FastAPI(title="exam-trainer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Cache-busts /static on every restart, same trick as writing.
STATIC_VERSION = str(int(BASE_DIR.stat().st_mtime))

ADMIN_COOKIE = "exam_trainer_admin"


def _is_admin(request: Request) -> bool:
    candidate = request.cookies.get(ADMIN_COOKIE, "")
    return bool(settings.admin_token) and secrets.compare_digest(candidate, settings.admin_token)


@app.middleware("http")
async def protect_admin(request: Request, call_next):
    path = request.url.path
    if path == "/products" or path.startswith("/products/"):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex"
        return response
    if path == "/kouko" or path.startswith("/kouko/"):
        reviewed = kouko.release_state()["reviewed"]
        response = await call_next(request)
        # These resources share the learning app's network access boundary.
        response.headers["Cache-Control"] = "no-store"
        if not reviewed or path == "/kouko/materials" or path.startswith("/kouko/files/"):
            response.headers["X-Robots-Tag"] = "noindex"
        return response
    if path in {"/admin/login", "/api/admin/session"}:
        return await call_next(request)
    admin_page = path == "/admin" or path.startswith("/admin/")
    public_api = (
        request.method == "GET" and re.fullmatch(r"/api/exams/\d+/next", path)
    ) or (
        request.method == "POST" and re.fullmatch(r"/api/questions/\d+/answer", path)
    ) or (
        request.method == "POST"
        and re.fullmatch(r"/api/affiliate-resources/\d+/impression", path)
    )
    protected_api = path.startswith("/api/") and not public_api
    if (admin_page or protected_api) and not _is_admin(request):
        if protected_api:
            return JSONResponse({"detail": "管理者認証が必要です"}, status_code=401)
        destination = path + (("?" + request.url.query) if request.url.query else "")
        return RedirectResponse("/admin/login?next=" + destination, status_code=303)
    return await call_next(request)


class AdminLoginIn(BaseModel):
    token: str
    next: str = "/admin"


@app.post("/api/admin/session")
def admin_login(payload: AdminLoginIn) -> Response:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="管理トークンが未設定です")
    if not secrets.compare_digest(payload.token, settings.admin_token):
        raise HTTPException(status_code=401, detail="管理トークンが違います")
    destination = payload.next if payload.next.startswith("/admin") else "/admin"
    response = JSONResponse({"ok": True, "next": destination})
    response.set_cookie(ADMIN_COOKIE, settings.admin_token, httponly=True,
                        samesite="strict", secure=settings.secure_cookies)
    return response


@app.get("/health")
def health() -> dict:
    try:
        db.connection().execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - only on a broken disk
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # `web` reports reachability, not merely that a URL is configured — a stale
    # SEARXNG_API_URL previously read as healthy while every search came back
    # empty.
    return {
        "ok": True,
        "ollama": ollama_client.available(),
        "web": web.reachable(),
        "web_configured": web.available(),
    }


def _current_exam(exam_id: int | None) -> dict | None:
    exams = bank.list_exams()
    if not exams:
        return None
    if exam_id is None:
        return exams[0]
    return next((exam for exam in exams if exam["id"] == exam_id), exams[0])


def _page(request: Request, name: str, exam_id: int | None, **extra) -> HTMLResponse:
    exam = _current_exam(exam_id)
    context = {
        "request": request,
        "exams": bank.list_exams(),
        "exam": exam,
        "static_version": STATIC_VERSION,
        "counts": bank.queue_counts(exam["id"]) if exam else {"due": 0, "new": 0},
        "status_counts": bank.counts_by_status(exam["id"]) if exam else {},
        **extra,
    }
    return templates.TemplateResponse(request, name, context)


def _kouko_page(request: Request, name: str, **extra) -> HTMLResponse:
    product = kouko.load_product()
    return templates.TemplateResponse(request, name, {
        "request": request, "exam": None, "exams": [],
        "static_version": STATIC_VERSION, "product": product,
        "release": kouko.release_state(), "admin_view": _is_admin(request),
        "product_url": "/kouko", "product_name": "考古教材", "exam_name": "考古検定",
        "contents": ["考古資料の見方と旧石器", "縄文の集落と交流", "弥生の農具と集落",
                     "古墳と土器生産", "古代の宮殿、木簡、壁画"],
        **extra,
    })


@app.get("/kouko", response_class=HTMLResponse)
def kouko_landing(request: Request) -> HTMLResponse:
    return _kouko_page(request, "kouko_landing.html")


@app.get("/kouko/trial", response_class=HTMLResponse)
def kouko_trial(request: Request) -> HTMLResponse:
    return _kouko_page(request, "kouko_trial.html",
                       trial_questions=kouko.trial_payload(kouko.load_product()))


@app.get("/kouko/sample", response_class=HTMLResponse)
def kouko_sample(request: Request) -> HTMLResponse:
    return _kouko_page(request, "kouko_sample.html",
                       sample=kouko.sample_questions(kouko.load_product()))


@app.get("/kouko/materials", response_class=HTMLResponse)
def kouko_materials(request: Request) -> HTMLResponse:
    return _kouko_page(request, "kouko_materials.html", artifacts=kouko.artifacts())


@app.get("/kouko/files/{asset_id}")
def kouko_file(asset_id: str, download: bool = False) -> FileResponse:
    asset = next((item for item in kouko.artifacts() if item["id"] == asset_id), None)
    if asset is None or not asset["available"]:
        raise HTTPException(status_code=404, detail="資料が見つかりません")
    if not asset["current"]:
        raise HTTPException(status_code=409, detail="資料は版の確認・更新待ちです")
    return FileResponse(asset["path"], media_type=asset["media_type"],
                        filename=asset["path"].name,
                        content_disposition_type="attachment" if download else "inline")


class KoukoAnswerIn(BaseModel):
    question_id: int
    chosen: Literal[0, 1, 2, 3]


@app.post("/kouko/trial/answer")
def kouko_answer(payload: KoukoAnswerIn) -> dict:
    result = kouko.check_answer(payload.question_id, payload.chosen)
    if result is None:
        raise HTTPException(status_code=404, detail="無料体験の問題ではありません")
    return result


def _editorial_product(product_id: str) -> dict:
    try:
        return products.load_product(product_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="教材が見つかりません")


def _product_page(request: Request, product_id: str, template: str, **extra) -> HTMLResponse:
    product = _editorial_product(product_id)
    return templates.TemplateResponse(request, template, {
        "request": request, "exam": None, "exams": [], "product": product,
        "static_version": STATIC_VERSION, "admin_view": _is_admin(request),
        "product_url": f"/products/{product_id}", "product_name": product["exam_name"] + "の教材",
        "exam_name": product["exam_name"], "contents": product["contents"],
        "release": products.release_state(product_id), **extra,
    })


@app.get("/products", response_class=HTMLResponse)
def product_catalog(request: Request) -> HTMLResponse:
    entries = [{"name": "考古検定 入門クラス", "url": "/kouko", "count": 50,
                "reviewed": kouko.release_state()["reviewed"]}]
    for product_id, name in products.EXAMS.items():
        product = products.load_product(product_id)
        entries.append({"name": name, "url": f"/products/{product_id}",
                        "count": len(product["questions"]), "reviewed": products.release_state(product_id)["reviewed"]})
    return templates.TemplateResponse(request, "product_catalog.html", {
        "request": request, "exam": None, "exams": [], "static_version": STATIC_VERSION,
        "entries": entries,
    })


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_landing(request: Request, product_id: str) -> HTMLResponse:
    return _product_page(request, product_id, "product_landing.html")


@app.get("/products/{product_id}/trial", response_class=HTMLResponse)
def product_trial(request: Request, product_id: str) -> HTMLResponse:
    product = _editorial_product(product_id)
    return _product_page(request, product_id, "kouko_trial.html",
                         trial_questions=kouko.trial_payload(product))


@app.get("/products/{product_id}/sample", response_class=HTMLResponse)
def product_sample(request: Request, product_id: str) -> HTMLResponse:
    product = _editorial_product(product_id)
    return _product_page(request, product_id, "kouko_sample.html", sample=kouko.sample_questions(product))


@app.get("/products/{product_id}/materials", response_class=HTMLResponse)
def product_materials(request: Request, product_id: str) -> HTMLResponse:
    _editorial_product(product_id)
    return _product_page(request, product_id, "kouko_materials.html", artifacts=products.artifacts(product_id))


@app.get("/products/{product_id}/files/{asset_id}")
def product_file(product_id: str, asset_id: str, download: bool = False) -> FileResponse:
    _editorial_product(product_id)
    asset = next((item for item in products.artifacts(product_id) if item["id"] == asset_id), None)
    if asset is None or not asset["available"]:
        raise HTTPException(status_code=404, detail="資料が見つかりません")
    if not asset["current"]:
        raise HTTPException(status_code=409, detail="資料は版の確認・更新待ちです")
    return FileResponse(asset["path"], media_type=asset["media_type"], filename=asset["path"].name,
                        content_disposition_type="attachment" if download else "inline")


@app.post("/products/{product_id}/trial/answer")
def product_answer(product_id: str, payload: KoukoAnswerIn) -> dict:
    _editorial_product(product_id)
    result = products.check_answer(product_id, payload.question_id, payload.chosen)
    if result is None:
        raise HTTPException(status_code=404, detail="無料体験の問題ではありません")
    return result


@app.get("/", response_class=HTMLResponse)
def index(request: Request, exam_id: int | None = None, node: str = "") -> HTMLResponse:
    exam = _current_exam(exam_id)
    question = bank.next_question(exam["id"], node) if exam else None
    return _page(
        request, "study.html", exam_id,
        question=question,
        node=node,
        syllabus=bank.list_syllabus(exam["id"]) if exam else [],
    )


@app.get("/weakness", response_class=HTMLResponse)
def weakness(request: Request, exam_id: int | None = None) -> HTMLResponse:
    exam = _current_exam(exam_id)
    return _page(
        request, "weakness.html", exam_id,
        stats=bank.node_stats(exam["id"]) if exam else [],
        recent=bank.recent_reviews(exam["id"], 20) if exam else [],
    )


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/admin") -> HTMLResponse:
    return templates.TemplateResponse(request, "admin_login.html", {
        "request": request, "next": next, "static_version": STATIC_VERSION,
    })


@app.get("/admin/bank", response_class=HTMLResponse)
def bank_page(
    request: Request,
    exam_id: int | None = None,
    status: str = "",
    node: str = "",
    q: str = "",
    generate: str = "",
) -> HTMLResponse:
    exam = _current_exam(exam_id)
    questions = bank.list_questions(exam["id"], status=status, node_prefix=node, query=q) if exam else []
    return _page(
        request, "bank.html", exam_id,
        questions=questions,
        status=status,
        node=node,
        query=q,
        syllabus=bank.list_syllabus(exam["id"]) if exam else [],
        jobs=jobs.list_for_exam(exam["id"], 5) if exam else [],
        has_web=web.available(),
        search_options=web.scope_options(),
        search_default=web.current_scope(),
        # Set when arriving from a weakness-tree branch that has no questions,
        # so the dialog is already open on the node that sent you here.
        open_generate=bool(generate) and bool(node),
        admin_view=True,
    )


@app.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request, exam_id: int | None = None) -> HTMLResponse:
    from . import affiliate

    exam = _current_exam(exam_id)
    syllabus = bank.list_syllabus(exam["id"]) if exam else []
    outline = "\n".join(
        f"{node['path']} {node['title']}" + (f" | {node['keywords']}" if node["keywords"] else "")
        for node in syllabus
    )
    return _page(request, "settings.html", exam_id, syllabus=syllabus, outline=outline,
                 affiliate_resources=affiliate.list_for_exam(exam["id"]) if exam else [],
                 admin_view=True)


@app.get("/admin")
def admin_index() -> RedirectResponse:
    return RedirectResponse("/admin/bank", status_code=303)


@app.get("/bank")
def legacy_bank() -> RedirectResponse:
    return RedirectResponse("/admin/bank", status_code=303)


@app.get("/settings")
def legacy_settings() -> RedirectResponse:
    return RedirectResponse("/admin/settings", status_code=303)


# --- API -----------------------------------------------------------------

class ExamIn(BaseModel):
    name: str


@app.post("/api/exams")
def create_exam(payload: ExamIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="試験名を入力してください")
    return {"id": bank.create_exam(name)}


@app.post("/api/exams/{exam_id}/delete")
def delete_exam(exam_id: int) -> dict:
    bank.delete_exam(exam_id)
    return {"ok": True}


class SyllabusIn(BaseModel):
    outline: str


@app.post("/api/exams/{exam_id}/syllabus")
def set_syllabus(exam_id: int, payload: SyllabusIn) -> dict:
    nodes = bank.parse_syllabus_outline(payload.outline)
    if not nodes:
        raise HTTPException(
            status_code=400,
            detail="項目を読み取れませんでした。各行を「1.2 タイトル」の形式にしてください",
        )
    bank.set_syllabus(exam_id, nodes)
    return {"count": len(nodes)}


class QuestionIn(BaseModel):
    node_path: str
    stem: str
    choices: list[str]
    answer: int
    explanation: str = ""
    evidence: str = ""
    source_refs: list[str] = []
    status: str = "verified"


@app.post("/api/exams/{exam_id}/questions")
def add_question(exam_id: int, payload: QuestionIn) -> dict:
    from . import checks

    problems = checks.check(payload.stem, payload.choices, payload.answer)
    if problems:
        raise HTTPException(status_code=400, detail=" / ".join(problems))
    question_id = bank.add_question(
        exam_id,
        payload.node_path,
        payload.stem,
        payload.choices,
        payload.answer,
        explanation=payload.explanation,
        evidence=payload.evidence,
        source_refs=payload.source_refs,
        status=payload.status,
        origin="manual",
    )
    return {"id": question_id}


class StatusIn(BaseModel):
    status: str
    hold_reason: str = ""


@app.post("/api/questions/{question_id}/status")
def set_question_status(question_id: int, payload: StatusIn) -> dict:
    try:
        bank.set_status(question_id, payload.status, payload.hold_reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/questions/{question_id}/delete")
def delete_question(question_id: int) -> dict:
    bank.delete_question(question_id)
    return {"ok": True}


class AnswerIn(BaseModel):
    chosen: int | None = None
    elapsed_ms: int = 0
    unsure: bool = False


@app.post("/api/questions/{question_id}/answer")
def answer(question_id: int, payload: AnswerIn) -> JSONResponse:
    from . import affiliate

    try:
        result = bank.answer(question_id, payload.chosen, payload.elapsed_ms, payload.unsure)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    question = bank.get_question(question_id)
    result["affiliate_resource"] = (
        affiliate.for_node(question["exam_id"], question["node_path"]) if question else None
    )
    return JSONResponse(result)


class AffiliateResourceIn(BaseModel):
    node_path: str
    title: str
    url: str
    reason: str = ""


@app.post("/api/exams/{exam_id}/affiliate-resources")
def save_affiliate_resource(exam_id: int, payload: AffiliateResourceIn) -> JSONResponse:
    from . import affiliate
    try:
        resource = affiliate.upsert(exam_id, payload.node_path, payload.title, payload.url, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(resource)


class AffiliateActiveIn(BaseModel):
    active: bool


@app.post("/api/affiliate-resources/{resource_id}/active")
def set_affiliate_resource_active(resource_id: int, payload: AffiliateActiveIn) -> dict:
    from . import affiliate
    affiliate.set_active(resource_id, payload.active)
    return {"ok": True}


class AffiliateEventIn(BaseModel):
    question_id: int | None = None


@app.post("/api/affiliate-resources/{resource_id}/impression")
def record_affiliate_impression(resource_id: int, payload: AffiliateEventIn) -> dict:
    from . import affiliate
    try:
        affiliate.record(resource_id, payload.question_id, "impression")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/affiliate-resources/{resource_id}/click")
def affiliate_click(resource_id: int, question_id: int | None = None) -> RedirectResponse:
    from . import affiliate
    try:
        target = affiliate.click_target(resource_id, question_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse(target, status_code=303)


class GenerateIn(BaseModel):
    node_path: str
    target: int = 5
    search_scope: Literal["sites", "yacy", "searxng"] | None = None


def _check_search(scope: str | None) -> str:
    scope = scope or web.current_scope()
    if scope not in {option["id"] for option in web.scope_options()}:
        raise HTTPException(400, "検索範囲を選び直してください")
    with web.search_mode(scope):
        if not web.available():
            raise HTTPException(400, "検索先が未設定です（WEB_SEARCH_API_URL / SEARXNG_API_URL）")
        if not web.reachable():
            raise HTTPException(400, "検索基盤に接続できません。サービスの稼働を確認してください")
    return scope


@app.post("/api/exams/{exam_id}/generate")
def start_generation(exam_id: int, payload: GenerateIn) -> JSONResponse:
    scope = _check_search(payload.search_scope)
    if not payload.node_path.strip():
        raise HTTPException(status_code=400, detail="シラバス項目を選んでください")
    try:
        job = jobs.enqueue(exam_id, payload.node_path.strip(), payload.target, search_scope=scope)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse(job)


class FillIn(BaseModel):
    target: int = 5
    # The worker runs one job at a time and each takes minutes, so an unbounded
    # queue would be hours deep and unclear when it would end.
    limit: int = 8
    search_scope: Literal["sites", "yacy", "searxng"] | None = None


@app.post("/api/exams/{exam_id}/generate-missing")
def start_bulk_generation(exam_id: int, payload: FillIn) -> JSONResponse:
    scope = _check_search(payload.search_scope)
    target = max(1, payload.target)
    pending = bank.nodes_needing_questions(exam_id, target, limit=max(1, payload.limit))
    if not pending:
        raise HTTPException(
            status_code=400,
            detail=f"すべての項目が目標の{target}問に達しています",
        )
    conflicts = [job for job in jobs.active(exam_id)
                 if job["node_path"] in {node["path"] for node in pending} and job["search_scope"] != scope]
    if conflicts:
        raise HTTPException(409, "別の検索範囲で生成中の項目があります。終了後に再実行してください")
    try:
        queued = [
            {"node_path": node["path"], "title": node["title"], "job_id": jobs.enqueue(
                exam_id, node["path"], target, search_scope=scope,
            )["id"]}
            for node in pending
        ]
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return JSONResponse({"queued": queued, "count": len(queued)})


@app.get("/api/exams/{exam_id}/missing")
def list_missing(exam_id: int, target: int = 5, limit: int = 8) -> JSONResponse:
    pending = bank.nodes_needing_questions(exam_id, max(1, target), limit=max(1, limit))
    return JSONResponse({"items": pending, "count": len(pending)})


class MaterialIn(BaseModel):
    node_path: str
    urls: list[str]


@app.post("/api/exams/{exam_id}/materials")
def add_materials(exam_id: int, payload: MaterialIn) -> JSONResponse:
    from . import materials

    node_path = payload.node_path.strip()
    if not node_path:
        raise HTTPException(status_code=400, detail="シラバス項目を選んでください")
    if not any(url.strip() for url in payload.urls):
        raise HTTPException(status_code=400, detail="URL を1つ以上入力してください")
    result = materials.add_from_urls(exam_id, node_path, payload.urls)
    if not result["added"]:
        raise HTTPException(
            status_code=400,
            detail="どのURLからも本文を取り出せませんでした: "
            + " / ".join(f"{item['url']} ({item['reason']})" for item in result["failed"][:3]),
        )
    return JSONResponse(result)


@app.get("/api/exams/{exam_id}/materials")
def list_materials(exam_id: int) -> JSONResponse:
    from . import materials

    return JSONResponse({"counts": materials.counts_by_node(exam_id)})


@app.get("/api/exams/{exam_id}/jobs")
def list_jobs(exam_id: int) -> JSONResponse:
    return JSONResponse({"items": jobs.list_for_exam(exam_id)})


@app.get("/api/exams/{exam_id}/next")
def next_question(exam_id: int, node: str = "") -> JSONResponse:
    question = bank.next_question(exam_id, node)
    counts = bank.queue_counts(exam_id)
    if question is None:
        return JSONResponse({"question": None, "counts": counts})
    # The answer index never leaves the server until the answer is submitted;
    # otherwise the correct choice is readable in devtools.
    served = {key: value for key, value in question.items() if key not in {"answer", "explanation", "evidence"}}
    return JSONResponse({"question": served, "counts": counts})
