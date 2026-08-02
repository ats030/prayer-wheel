"""Per-feed fetch outcome, kept outside the cache file.

失敗したフィードはキャッシュファイルを書き換えないので、「いつ試して何で落ちたか」は
そこには残らない。一度も成功していないフィードにはファイル自体が無い。実際に
shinryourimonogatari.com は61日、assets.wor.jp は9日ぶん古いままだったが、UI からは
「新着が無いフィード」と見分けが付かなかった（refresh_all のエラーはジョブバーが
消えると同時に失われる）。

失敗が続いているフィードだけを小さな JSON に持ち、成功したら消す。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from ..config import DATA_DIR

STATUS_FILE = DATA_DIR / "feed_status.json"

_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load() -> dict[str, dict]:
    """URL → {last_attempt, last_error, failing_since}。失敗中のフィードのみ。"""
    try:
        data = json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, STATUS_FILE)


def record_failure(url: str, exc: BaseException) -> None:
    """全更新は6並列なので、読み出し〜書き戻しをロックで囲む。"""
    message = f"{type(exc).__name__}: {exc}"[:300]
    with _lock:
        data = load()
        entry = data.get(url) or {}
        data[url] = {
            "last_attempt": _now(),
            "last_error": message,
            # 「いつから壊れているか」は残す。毎回上書きすると経過が分からない。
            "failing_since": entry.get("failing_since") or _now(),
        }
        _save(data)


def record_success(url: str) -> None:
    with _lock:
        data = load()
        if data.pop(url, None) is not None:
            _save(data)


def forget(url: str) -> None:
    """フィード削除時に status も片付ける。"""
    record_success(url)
