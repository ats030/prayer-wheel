"""識別を、リクエストの寿命から切り離して走らせるための小さな置き場。

ブラウザが待っている間だけ生きる作りだと、画面を更新したり間違って戻ったりした
瞬間に、走らせた識別の答えが行き場をなくす。Ollama では1分ほどかかるので、
その1分のあいだ画面を触れないのは実用に堪えない。

置くのは**結果だけ**。写真は仕事が走っているあいだ、その仕事の変数の中にしか
存在せず、終わった時点で捨てる。つまり画像がサーバーに居る時間は、これまで
リクエストが生きていた時間と変わらない。ディスクにも書かない。

プロセスが再起動すれば全部消える。それでよい。消えたら画面には「もう一度
お試しください」と出るだけで、記録は端末の側にある。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

# 結果を取りに来ないまま放置されたぶんの寿命。ブラウザを閉じたまま戻らない人がいる
TTL_SECONDS = 600
# 同時に抱える上限。超えたら古いものから捨てる (メモリを青天井にしない)
MAX_JOBS = 32

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def _sweep(now: float) -> None:
    for key in [k for k, v in _JOBS.items() if now - v["at"] > TTL_SECONDS]:
        _JOBS.pop(key, None)
    while len(_JOBS) > MAX_JOBS:
        oldest = min(_JOBS, key=lambda k: _JOBS[k]["at"])
        _JOBS.pop(oldest, None)


def start(owner: str = "") -> str:
    """仕事を1つ立てて、その札を返す。owner は公開版のログイン利用者を縛るため。"""
    job_id = uuid.uuid4().hex
    now = time.time()
    with _LOCK:
        _sweep(now)
        _JOBS[job_id] = {"status": "running", "owner": owner, "at": now}
    return job_id


def finish(job_id: str, result: dict[str, Any]) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(status="done", result=result, at=time.time())


def fail(job_id: str, status_code: int, detail: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.update(status="error", status_code=int(status_code), detail=detail, at=time.time())


def get(job_id: str, owner: str = "") -> dict[str, Any] | None:
    """札に対応する仕事を返す。持ち主が違えば見えないものとして扱う。"""
    with _LOCK:
        _sweep(time.time())
        job = _JOBS.get(str(job_id))
        if job is None or job.get("owner", "") != owner:
            return None
        return dict(job)


def running() -> int:
    with _LOCK:
        return sum(1 for job in _JOBS.values() if job["status"] == "running")
