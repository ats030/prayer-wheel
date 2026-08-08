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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

from . import bank, db, jobs, ollama_client, web
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


@app.post("/api/exams/{exam_id}/generate")
def start_generation(exam_id: int, payload: GenerateIn) -> JSONResponse:
    if not web.available():
        raise HTTPException(
            status_code=400,
            detail="SEARXNG_API_URL が未設定です。根拠を集められないため生成できません",
        )
    # Told here rather than after a multi-minute job that quietly collects
    # nothing. The two causes need different fixes, so they get different text.
    if not web.reachable():
        raise HTTPException(
            status_code=400,
            detail=(
                f"SearXNG ({settings.searxng_url}) に接続できません。"
                "URL と searxng.service の稼働を確認してください"
            ),
        )
    if not payload.node_path.strip():
        raise HTTPException(status_code=400, detail="シラバス項目を選んでください")
    job = jobs.enqueue(exam_id, payload.node_path.strip(), payload.target)
    return JSONResponse(job)


class FillIn(BaseModel):
    target: int = 5
    # The worker runs one job at a time and each takes minutes, so an unbounded
    # queue would be hours deep and unclear when it would end.
    limit: int = 8


@app.post("/api/exams/{exam_id}/generate-missing")
def start_bulk_generation(exam_id: int, payload: FillIn) -> JSONResponse:
    if not web.available():
        raise HTTPException(
            status_code=400,
            detail="SEARXNG_API_URL が未設定です。根拠を集められないため生成できません",
        )
    if not web.reachable():
        raise HTTPException(
            status_code=400,
            detail=(
                f"SearXNG ({settings.searxng_url}) に接続できません。"
                "URL と searxng.service の稼働を確認してください"
            ),
        )
    target = max(1, payload.target)
    pending = bank.nodes_needing_questions(exam_id, target, limit=max(1, payload.limit))
    if not pending:
        raise HTTPException(
            status_code=400,
            detail=f"すべての項目が目標の{target}問に達しています",
        )
    queued = [
        {"node_path": node["path"], "title": node["title"], "job_id": jobs.enqueue(
            exam_id, node["path"], target,
        )["id"]}
        for node in pending
    ]
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
