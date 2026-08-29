"""In-process registry for the slow operations the UI must not block on.

Refreshing 39 feeds, LLM scoring and profile generation all take from seconds
to minutes. Streamlit rendered those behind a blocking ``st.progress`` that
froze the whole page; here the request starts a worker thread, returns a job
id, and the browser polls ``/api/jobs/{id}`` for progress.

State is deliberately in-memory only: a restart cancels nothing that matters
(refresh results are already written to the feed cache item by item).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    kind: str
    total: int = 0
    done: int = 0
    status: str = "running"  # running | finished | failed
    message: str = ""
    errors: list[str] = field(default_factory=list)
    # 完了時にクライアントへ返す値（検出したフィード候補、生成したタグなど）
    result: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "total": self.total,
            "done": self.done,
            "status": self.status,
            "message": self.message,
            "errors": self.errors[:20],
            "error_count": len(self.errors),
            "result": self.result,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1),
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
# 同じ種類のジョブの二重起動を防ぐ（「全更新」連打対策）
_active_by_kind: dict[str, str] = {}


def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def active(kind: str) -> Job | None:
    with _lock:
        job_id = _active_by_kind.get(kind)
        job = _jobs.get(job_id) if job_id else None
    return job if job and job.status == "running" else None


def running_jobs() -> list[Job]:
    """Return all running jobs."""
    with _lock:
        return [j for j in _jobs.values() if j.status == "running"]


def start(kind: str, fn, *, total: int = 0, message: str = "") -> Job:
    """Run ``fn(job)`` on a worker thread. Returns the running job if one exists."""
    existing = active(kind)
    if existing is not None:
        return existing

    job = Job(id=uuid.uuid4().hex[:12], kind=kind, total=total, message=message)
    with _lock:
        _jobs[job.id] = job
        _active_by_kind[kind] = job.id
        _prune_locked()

    def _run() -> None:
        try:
            fn(job)
            job.status = "finished"
        except Exception as exc:  # noqa: BLE001 — surfaced to the UI as-is
            job.status = "failed"
            job.message = str(exc)
        finally:
            job.finished_at = time.time()

    threading.Thread(target=_run, name=f"job-{kind}-{job.id}", daemon=True).start()
    return job


def _prune_locked(keep: int = 40) -> None:
    if len(_jobs) <= keep:
        return
    finished = sorted(
        (j for j in _jobs.values() if j.status != "running"),
        key=lambda j: j.finished_at or 0,
    )
    for job in finished[: len(_jobs) - keep]:
        _jobs.pop(job.id, None)
