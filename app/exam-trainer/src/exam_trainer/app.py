"""exam-trainer: FastAPI routes (port 8522).

Screens follow the arrangement settled in the writing editor: the toolbar acts
on the document (here: the exam), and each tab owns both the control that runs
something and the result it produces.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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


@app.get("/health")
def health() -> dict:
    try:
        db.connection().execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - only on a broken disk
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "ollama": ollama_client.available(), "web": web.available()}


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


@app.get("/bank", response_class=HTMLResponse)
def bank_page(
    request: Request,
    exam_id: int | None = None,
    status: str = "",
    node: str = "",
    q: str = "",
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
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, exam_id: int | None = None) -> HTMLResponse:
    exam = _current_exam(exam_id)
    syllabus = bank.list_syllabus(exam["id"]) if exam else []
    outline = "\n".join(
        f"{node['path']} {node['title']}" + (f" | {node['keywords']}" if node["keywords"] else "")
        for node in syllabus
    )
    return _page(request, "settings.html", exam_id, syllabus=syllabus, outline=outline)


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
    try:
        result = bank.answer(question_id, payload.chosen, payload.elapsed_ms, payload.unsure)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(result)


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
    if not payload.node_path.strip():
        raise HTTPException(status_code=400, detail="シラバス項目を選んでください")
    job = jobs.enqueue(exam_id, payload.node_path.strip(), payload.target)
    return JSONResponse(job)


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
