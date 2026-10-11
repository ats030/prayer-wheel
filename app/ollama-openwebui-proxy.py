#!/usr/bin/env python3
"""Expose a local Ollama-compatible endpoint backed by Open WebUI."""

from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


load_dotenv(Path.home() / ".env")

LISTEN_HOST = env("OLLAMA_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(env("OLLAMA_PROXY_PORT", "11434"))
OPENWEBUI_BASE_URL = env("OPENWEBUI_BASE_URL").rstrip("/")
OPENWEBUI_API_KEY = env("OPENWEBUI_API_KEY")
TARGET_BASE_URL = env("OLLAMA_PROXY_TARGET_URL") or (
    f"{OPENWEBUI_BASE_URL}/ollama" if OPENWEBUI_BASE_URL else ""
)
TARGET_BASE_URL = TARGET_BASE_URL.rstrip("/")
INTERACTIVE_TARGETS = tuple(
    value.strip().rstrip("/")
    for value in env("OLLAMA_PROXY_INTERACTIVE_TARGETS", TARGET_BASE_URL).split(",")
    if value.strip()
)


def routes_interactive(targets: tuple[str, ...], default: str) -> bool:
    """対話先が1つでも、既定の転送先と違えばそこへ送る。

    件数で判定すると、対話専用ワーカーだけを指定したとき qwen が本体 ollama に
    戻り、gemma の背景処理と待ち行列を奪い合う (ats030-ltlgv)。
    """
    return bool(targets) and targets != (default,)


ROUTE_INTERACTIVE = routes_interactive(INTERACTIVE_TARGETS, TARGET_BASE_URL)
INTERACTIVE_STICKY_WAIT =float(env("OLLAMA_PROXY_INTERACTIVE_STICKY_WAIT", "5"))
INTERACTIVE_QUEUE_TIMEOUT = float(env("OLLAMA_PROXY_INTERACTIVE_QUEUE_TIMEOUT", "120"))
REQUEST_TIMEOUT = int(env("OLLAMA_PROXY_TIMEOUT", "600"))
GENERATION_QUEUE_TIMEOUT = float(env("OLLAMA_PROXY_QUEUE_TIMEOUT", "5"))
GENERATION_RETRY_AFTER = int(env("OLLAMA_PROXY_RETRY_AFTER", "30"))
MAX_GENERATIONS = int(env("OLLAMA_PROXY_MAX_GENERATIONS", "3"))
MAX_BACKGROUND_GENERATIONS = int(env("OLLAMA_PROXY_MAX_BACKGROUND_GENERATIONS", "2"))
MAX_BACKGROUND_QUEUE = int(env("OLLAMA_PROXY_MAX_BACKGROUND_QUEUE", "20"))
INTERACTIVE_CONTEXT = int(env("OLLAMA_PROXY_INTERACTIVE_CONTEXT", "65536"))
BATCH_CONTEXT = int(env("OLLAMA_PROXY_BATCH_CONTEXT", "16384"))
WORKLOAD_HEADER = "X-Ollama-Workload-Class"
WORKLOAD_MODELS = {
    "interactive": env("OLLAMA_PROXY_INTERACTIVE_MODEL", "qwen3.8:27b"),
    "batch-light": env("OLLAMA_PROXY_BATCH_LIGHT_MODEL", "gemma4:12b"),
    "batch-heavy": env("OLLAMA_PROXY_BATCH_HEAVY_MODEL", "qwen3.8:27b"),
}
VIRTUAL_MODELS = {f"auto-{kind}": kind for kind in WORKLOAD_MODELS}
OPENCODE_CLIENT_APP = "opencode"
OPENCODE_LEASE_SECONDS = float(env("OLLAMA_PROXY_OPENCODE_LEASE", "60"))
BACKGROUND_STARVATION_SECONDS = float(
    env("OLLAMA_PROXY_BACKGROUND_STARVATION", "600")
)
# X-Client-App を名乗るバッチ要求だけ、ゲート取得後に他の常駐モデルを
# keep_alive=0 で退避させる (ats030-pe2x)。_generation_gate は生成要求を
# 1本に絞るため、ここに到達した時点で他の生成要求 (opencodeの対話要求も
# 同じproxyを通る) はこのproxyを通っていない。よって /api/ps に映る
# モデルは使用中ではなく、安全に退避できる。本番で問題が出た場合に
# 再デプロイ無しで切れるよう既定で有効にしておく。
EVICT_COMPETITORS_ENABLED = env("OLLAMA_PROXY_EVICT_COMPETITORS", "1") not in ("0", "false", "no")
EVICT_TIMEOUT = float(env("OLLAMA_PROXY_EVICT_TIMEOUT", "10"))
# 未設定 (既定0) は従来どおり _generation_gate による単一直列化のみ。
# ホストの実効 VRAM を実測した上で設定した場合だけ、常駐モデル合計+対象
# モデルがこの予算に収まる限りゲートを介さず並行転送する (ats030-pe2x)。
VRAM_BUDGET_BYTES = int(env("OLLAMA_PROXY_VRAM_BUDGET_BYTES", "0") or "0")
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(value.strip())
    for value in env("OLLAMA_PROXY_ALLOWED_NETWORKS", "127.0.0.0/8").split(",")
    if value.strip()
)
TRUSTED_NETWORKS = tuple(
    ipaddress.ip_network(value.strip())
    for value in env("OLLAMA_PROXY_TRUSTED_NETWORKS", "127.0.0.0/8").split(",")
    if value.strip()
)
ALLOWED_ORIGINS = {
    value.strip()
    for value in env("OLLAMA_PROXY_ALLOWED_ORIGINS").split(",")
    if value.strip()
}

# 使用量の記録。ローカル LLM は全アプリがこの proxy を通るので、ここが唯一の
# 計測点になる。~/data はバックアップ対象 (~/CLAUDE.md「データの保全」)。
# 再パースできる元ログが無いため、失うと戻らない。
USAGE_LOG_DIR = Path(env("OLLAMA_PROXY_USAGE_DIR")
                     or str(Path.home() / "data" / "ollama-proxy"))
USAGE_LOG_ENABLED = env("OLLAMA_PROXY_USAGE_LOG", "1") not in ("0", "false", "no")
# 応答の末尾だけ保持する。ストリームは最終行に、非ストリームは本体末尾に
# トークン数が入るため、頭は要らない。転送そのものは素通しのまま。
USAGE_TAIL_BYTES = 256 * 1024
# 計測するのは生成と埋め込みだけ。/api/tags や /api/ps は1日1万件来るが
# トークンを消費しないので記録しても雑音になる。
GENERATION_PATHS = frozenset({
    "/api/generate", "/api/chat", "/api/embed", "/api/embeddings",
    "/v1/chat/completions", "/v1/completions", "/v1/embeddings",
})
USAGE_PATHS = GENERATION_PATHS
_usage_lock = threading.Lock()
# 生成系は対話用1枠を予約し、backgroundを最大2本まで通す。待機中は対話を
# 優先する一方、長時間待ったbackgroundはagingで飢餓を防ぐ。管理APIは塞がない。


class GenerationScheduler:
    """対話優先の生成枠とbackground agingをまとめて管理する。"""

    def __init__(self, clock=time.monotonic, max_active=None, max_background=None,
                 max_background_queue=None):
        self.clock = clock
        self.max_active = max_active or MAX_GENERATIONS
        self.max_background = max_background or MAX_BACKGROUND_GENERATIONS
        self.max_background_queue = (max_background_queue if max_background_queue is not None
                                     else MAX_BACKGROUND_QUEUE)
        self.condition = threading.Condition()
        self.active: dict[int, dict] = {}
        self.waiting: dict[int, dict] = {}
        self.background_order: deque[int] = deque()
        self.next_ticket = 1
        self.opencode_lease_until = 0.0
        self.last_received_at: float | None = None

    def reset(self) -> None:
        """self-test用。稼働中には呼ばない。"""
        with self.condition:
            self.active.clear()
            self.waiting.clear()
            self.background_order.clear()
            self.next_ticket = 1
            self.opencode_lease_until = 0.0
            self.last_received_at = None
            self.condition.notify_all()

    def acquire(self, kind: str, model: str, timeout: float | None) -> int | None:
        now = self.clock()
        with self.condition:
            if (kind == "background"
                    and len(self.background_order) >= self.max_background_queue):
                return None
            ticket = self.next_ticket
            self.next_ticket += 1
            entry = {"ticket": ticket, "kind": kind, "model": model or "unknown",
                     "queued_at": now}
            self.waiting[ticket] = entry
            if kind == "background":
                self.background_order.append(ticket)
            deadline = None if timeout is None else now + timeout
            try:
                while not self._may_start(ticket):
                    if deadline is not None:
                        remaining = deadline - self.clock()
                        if remaining <= 0:
                            return None
                    else:
                        remaining = None
                    # lease/agingの境界でも再評価できるよう、通知だけに依存しない。
                    wait_for = 1.0 if remaining is None else min(remaining, 1.0)
                    self.condition.wait(timeout=wait_for)
                rescued_background = (
                    kind == "background"
                    and self.clock() - entry["queued_at"] >= BACKGROUND_STARVATION_SECONDS
                )
                self.active[ticket] = self.waiting.pop(ticket)
                if kind == "background":
                    self.background_order.remove(ticket)
                if rescued_background:
                    # aging済みを連続で通すとOpenCodeが再び飢餓になる。今回の
                    # 1件以外は待機時計をここから再開する。
                    reset_at = self.clock()
                    for other in self.background_order:
                        self.waiting[other]["queued_at"] = reset_at
                self.active[ticket]["started_at"] = self.clock()
                return ticket
            finally:
                if ticket in self.waiting and (
                        deadline is not None and self.clock() >= deadline):
                    self.waiting.pop(ticket, None)
                    if ticket in self.background_order:
                        self.background_order.remove(ticket)

    def _may_start(self, ticket: int) -> bool:
        if len(self.active) >= self.max_active:
            return False
        entry = self.waiting[ticket]
        active_background = sum(
            item["kind"] == "background" for item in self.active.values()
        )
        if (entry["kind"] == "background"
                and active_background >= self.max_background):
            return False
        now = self.clock()
        oldest_background = (
            self.waiting.get(self.background_order[0]) if self.background_order else None
        )
        aged_background = bool(
            oldest_background
            and active_background < self.max_background
            and now - oldest_background["queued_at"] >= BACKGROUND_STARVATION_SECONDS
        )
        if aged_background:
            return ticket == oldest_background["ticket"]
        if entry["kind"] == "background":
            has_foreground = any(
                queued["kind"] != "background" for queued in self.waiting.values()
            )
            return (
                ticket == self.background_order[0]
                and not has_foreground
                and (self.max_active > 1 or now >= self.opencode_lease_until)
            )
        return True

    def received(self, ticket: int | None) -> None:
        with self.condition:
            if ticket in self.active:
                self.last_received_at = self.clock()

    def release(self, ticket: int | None) -> None:
        with self.condition:
            if ticket in self.active:
                if self.active[ticket]["kind"] == "opencode":
                    self.opencode_lease_until = self.clock() + OPENCODE_LEASE_SECONDS
                self.active.pop(ticket)
                self.condition.notify_all()

    def snapshot(self) -> dict:
        with self.condition:
            now = self.clock()
            active_background = sum(
                item["kind"] == "background" for item in self.active.values()
            )
            opencode_waiting = next(
                (item for item in self.waiting.values() if item["kind"] == "opencode"),
                None,
            )
            active = next(iter(self.active.values()), None)
            shown = opencode_waiting or active
            base = {
                "state": "idle",
                "model": "",
                "elapsed_seconds": 0,
                "queue_depth": len(self.waiting),
                "active_count": len(self.active),
                "background_free": max(0, self.max_background - active_background),
                "last_received_seconds": None,
            }
            if shown is None:
                return base
            queued = "started_at" not in shown
            started = shown.get("queued_at") if queued else shown["started_at"]
            base.update({
                "state": "queued" if queued else "generating",
                "model": shown["model"],
                "elapsed_seconds": max(0, int(now - started)),
                "last_received_seconds": (
                    None if queued or self.last_received_at is None
                    else max(0, int(now - self.last_received_at))
                ),
            })
            return base


class InteractiveRouter:
    """会話を通常は同じ上流へ固定し、混雑時だけ別上流へ逃がす。"""

    def __init__(self, targets: tuple[str, ...], clock=time.monotonic):
        self.targets = targets
        self.clock = clock
        self.condition = threading.Condition()
        self.active = [False] * len(targets)

    def acquire(self, session_key: str, sticky_wait: float,
                timeout: float) -> int | None:
        if not self.targets:
            return None
        preferred = int(session_key[:16], 16) % len(self.targets)
        started = self.clock()
        sticky_deadline = started + sticky_wait
        deadline = started + timeout
        with self.condition:
            while True:
                now = self.clock()
                if not self.active[preferred]:
                    self.active[preferred] = True
                    return preferred
                if now >= sticky_deadline:
                    for index in range(len(self.targets)):
                        if index != preferred and not self.active[index]:
                            self.active[index] = True
                            return index
                if now >= deadline:
                    return None
                wake_at = sticky_deadline if now < sticky_deadline else deadline
                self.condition.wait(timeout=max(0.01, wake_at - now))

    def release(self, index: int | None) -> None:
        if index is None:
            return
        with self.condition:
            self.active[index] = False
            self.condition.notify_all()

    def acquire_other(self, failed_index: int, timeout: float) -> int | None:
        """障害workerを除外し、残存workerが空くまで待つ。"""
        deadline = self.clock() + timeout
        with self.condition:
            while True:
                for index in range(len(self.targets)):
                    if index != failed_index and not self.active[index]:
                        self.active[index] = True
                        return index
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return None
                self.condition.wait(timeout=remaining)

    def reset(self) -> None:
        with self.condition:
            self.active = [False] * len(self.targets)
            self.condition.notify_all()


def conversation_key(body: bytes | None) -> str:
    """会話先頭だけから非永続のrouting keyを作る。本文は保存しない。"""
    anchor: object = ""
    if body:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            messages = payload.get("messages")
            if isinstance(messages, list) and messages:
                anchor = messages[:2]
            else:
                anchor = str(payload.get("prompt") or "")[:4096]
    serialized = json.dumps(anchor, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(serialized).hexdigest()


_generation_gate = GenerationScheduler()
_interactive_router = InteractiveRouter(INTERACTIVE_TARGETS)
# VRAM予算判定用に /api/ps で観測したモデルサイズを溜めるキャッシュ。
# プロセス起動直後などサイズ未観測のモデルは admit_without_gate() 側で
# 安全側 (フォールバック) に倒すため、ここが空でも実害は無い。
_model_size_lock = threading.Lock()
_model_size_cache: dict[str, int] = {}


def require_config() -> None:
    missing = []
    if not TARGET_BASE_URL:
        missing.append("OPENWEBUI_BASE_URL or OLLAMA_PROXY_TARGET_URL")
    if not OPENWEBUI_API_KEY:
        missing.append("OPENWEBUI_API_KEY")
    if missing:
        raise SystemExit("Missing required config: " + ", ".join(missing))


def _usage_from_object(d: dict) -> dict | None:
    """1個の JSON オブジェクトからトークン数と実行時間を取り出す。

    Ollama native (/api/generate, /api/chat) は最終オブジェクトに
    prompt_eval_count / eval_count / total_duration(ナノ秒) を必ず入れる。
    OpenAI 互換 (/v1/chat/completions) は usage を入れるが、ストリーム時は
    stream_options.include_usage を送ったときだけなので取れないことがある。
    """
    if not isinstance(d, dict):
        return None
    if "prompt_eval_count" in d or "eval_count" in d:
        return {
            "model": d.get("model") or "",
            "input": int(d.get("prompt_eval_count") or 0),
            "output": int(d.get("eval_count") or 0),
            # ナノ秒。total_duration は load_duration を含む合計。
            "duration_ms": round((d.get("total_duration") or 0) / 1e6),
            # モデルの読み込みに掛かった分。大きい行は追い出しが起きた証拠。
            "load_ms": round((d.get("load_duration") or 0) / 1e6),
        }
    usage = d.get("usage")
    if isinstance(usage, dict) and (
            "prompt_tokens" in usage or "input_tokens" in usage):
        return {
            "model": d.get("model") or "",
            "input": int(usage.get("prompt_tokens")
                         or usage.get("input_tokens") or 0),
            "output": int(usage.get("completion_tokens")
                          or usage.get("output_tokens") or 0),
            "duration_ms": 0,
            "load_ms": 0,
        }
    return None


def _response_metadata(d: dict) -> dict:
    """応答本文を保存せず、終了理由とtool-callかどうかだけを採る。"""
    if not isinstance(d, dict):
        return {}
    reason = d.get("done_reason") or ""
    tool_call = False
    for choice in d.get("choices") or []:
        reason = choice.get("finish_reason") or reason
        message = choice.get("message") or choice.get("delta") or {}
        tool_call = tool_call or bool(message.get("tool_calls"))
    if reason == "tool_calls":
        tool_call = True
    result = {}
    if reason:
        result["finish_reason"] = str(reason)[:40]
    if tool_call:
        result["response_kind"] = "tool_call"
    elif reason:
        result["response_kind"] = "text"
    return result


def extract_usage(payload: bytes) -> dict | None:
    """応答の末尾からトークン数を取り出す。取れなければ None。

    4通りある。NDJSON ストリーム (Ollama native) / SSE ストリーム (OpenAI 互換) /
    それぞれの非ストリーム。いずれも欲しい値は末尾にあるので、後ろから見る。
    """
    if not payload:
        return None
    lines = payload.split(b"\n")
    usage = None
    metadata = {}
    for raw in reversed(lines[-200:]):
        line = raw.strip()
        if line.startswith(b"data:"):
            line = line[5:].strip()
        if not line.startswith(b"{"):
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            continue
        if usage is None:
            usage = _usage_from_object(obj)
        # SSE の usage 最終チャンクは choices: []。終了理由はその前の
        # チャンクにあるため、usage を見つけた後も末尾から遡る。
        if not metadata:
            metadata = _response_metadata(obj)
        if usage is not None and metadata:
            return {**usage, **metadata}
    if usage is not None or metadata:
        # usage が取れなくても終了理由だけは残す。計測不能な往復と、
        # 上流が途中で切った往復を後から見分けるのに要る。
        return {**(usage or {}), **metadata}
    # 非ストリームで本文に改行が入っている (整形済み JSON) 場合の保険。
    try:
        obj = json.loads(payload)
        usage = _usage_from_object(obj)
        return {**usage, **_response_metadata(obj)} if usage else None
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None


def request_model(body: bytes | None) -> str:
    """要求本文の model。応答に model が無い埋め込み系のための控え。"""
    if not body:
        return ""
    try:
        d = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return ""
    return d.get("model") or "" if isinstance(d, dict) else ""


def route_request(body: bytes | None, workload_header: str,
                  client_app: str) -> tuple[bytes | None, str, str]:
    """処理クラスを解決し、仮想モデルとnum_ctxを実モデル要求へ変換する。"""
    if not body:
        return body, "interactive", ""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return body, "interactive", ""
    if not isinstance(payload, dict):
        return body, "interactive", ""

    requested_model = str(payload.get("model") or "")
    alias_workload = VIRTUAL_MODELS.get(requested_model)
    workload = workload_header.strip().lower() or alias_workload
    if not workload:
        workload = ("interactive" if not client_app or client_app == OPENCODE_CLIENT_APP
                    else "batch-heavy")
    if workload not in WORKLOAD_MODELS:
        raise ValueError(f"{WORKLOAD_HEADER} must be one of: "
                         + ", ".join(WORKLOAD_MODELS))

    if alias_workload or workload_header:
        payload["model"] = WORKLOAD_MODELS[workload]
    context_limit = (INTERACTIVE_CONTEXT if workload == "interactive"
                     else BATCH_CONTEXT)
    options = payload.get("options")
    if not isinstance(options, dict):
        options = {}
        payload["options"] = options
    requested_context = options.get("num_ctx")
    if (not isinstance(requested_context, int) or requested_context <= 0
            or requested_context > context_limit):
        options["num_ctx"] = context_limit
    return (json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            workload, payload.get("model", ""))


def fetch_loaded_models() -> list[dict] | None:
    """/api/ps を叩いてロード中モデルの一覧を返す。失敗時は None。"""
    try:
        request = urllib.request.Request(
            TARGET_BASE_URL + "/api/ps",
            headers={
                "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=EVICT_TIMEOUT) as response:
            return json.load(response).get("models") or []
    except Exception:  # noqa: BLE001
        return None


def admit_without_gate(target_model: str) -> bool:
    """VRAM予算方式: ゲートを取らず並行転送してよいか判定する。

    OLLAMA_PROXY_VRAM_BUDGET_BYTES が未設定 (既定0) の環境では常に False を
    返し、従来どおり _generation_gate による単一直列化のみで動く。判定材料
    (対象モデルの観測済みサイズなど) が欠けている場合も安全側に倒して
    False を返す (OOM で常駐モデルを巻き込むよりゲート待ちの方が安全)。
    実測に基づく予算値の設定は運用側の責任とし、この関数は実測を代替しない
    (ats030-pe2x)。
    """
    if VRAM_BUDGET_BYTES <= 0 or not target_model:
        return False
    models = fetch_loaded_models()
    if models is None:
        return False
    loaded_total = 0
    target_loaded = False
    for model in models:
        name = model.get("name")
        size = model.get("size_vram")
        if name and isinstance(size, int):
            with _model_size_lock:
                _model_size_cache[name] = size
        if name == target_model:
            target_loaded = True
            continue
        if isinstance(size, int):
            loaded_total += size
    if target_loaded:
        # 既にロード済みのモデルへの追加要求は新規VRAM確保を伴わない。
        return True
    with _model_size_lock:
        target_size = _model_size_cache.get(target_model)
    if target_size is None:
        return False
    return loaded_total + target_size <= VRAM_BUDGET_BYTES


def evict_idle_competitors(target_model: str) -> None:
    """X-Client-Appを名乗るバッチのために、他の常駐モデルをkeep_alive=0で降ろす。

    呼び出し元は _generation_gate を取得済みであること。ゲートが生成要求を
    1本に絞っているため、この時点で /api/ps に映るモデルはこのproxyを通した
    生成には使われていない (opencodeの対話要求も同じproxyを通る)。

    keep_alive を渡すのは /api/generate (ネイティブ) だけにする。
    /v1/chat/completions (OpenAI互換) に送ると即アンロードになる
    (ollama-keepalive.py の実測。2026-08-22)。-1 (恒久) は使わない。

    失敗は個々に握りつぶし、他のモデルの退避や本来の転送を妨げない。
    """
    models = fetch_loaded_models()
    if models is None:
        return
    for model in models:
        name = model.get("name")
        if not name or name == target_model:
            continue
        try:
            payload = json.dumps({"model": name, "keep_alive": 0}).encode("utf-8")
            evict_request = urllib.request.Request(
                TARGET_BASE_URL + "/api/generate",
                data=payload,
                headers={
                    "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(evict_request, timeout=EVICT_TIMEOUT):
                pass
        except Exception:  # noqa: BLE001
            continue


def client_label(user_agent: str, x_client_app: str | None = None) -> str:
    """User-Agent を呼び出し元の目印に縮める。

    X-Client-App ヘッダがあればそれを優先して使う。
    アプリの区別はモデル名の方が当てになるので、これは補助として置く。
    """
    if x_client_app and x_client_app.strip():
        return x_client_app.strip()[:40]
    ua = (user_agent or "").strip()
    if not ua:
        return "unknown"
    head = ua.split()[0].split("/")[0].strip()
    return head[:40] or "unknown"


def log_usage(path: str, request_body: bytes | None, tail: bytes,
              user_agent: str, status: int, elapsed_ms: int,
              error: str = "", client_app: str | None = None) -> None:
    """1リクエスト1行で追記する。月ごとにファイルを分ける。

    月次にしておくと、読む側 (usage-viewer) が既存の mtime/size キャッシュを
    そのまま使えて、過去月を再パースしなくて済む。

    成否によらず必ず1行残す。ローカルLLMの運用で効くのは使用量よりも
    止まったことの方で、失敗を落とすと一番見たいものが見えなくなる。
    """
    usage = extract_usage(tail) or {}
    now = datetime.now(timezone.utc)
    record = {
        "ts": now.isoformat(timespec="seconds"),
        "path": path.split("?", 1)[0],
        # 埋め込みの応答には model が無いので要求側から採る。
        "model": usage.get("model") or request_model(request_body) or "unknown",
        "input": usage.get("input", 0),
        "output": usage.get("output", 0),
        "duration_ms": usage.get("duration_ms", 0),
        "load_ms": usage.get("load_ms", 0),
        # proxy から見た実測。Ollama が所要時間を申告しない経路 (OpenAI 互換)
        # でも埋まる代わり、キュー待ちと転送時間を含むので duration_ms とは別物。
        "elapsed_ms": elapsed_ms,
        # 上流の応答コード。0 は応答そのものが得られなかった (切断・タイムアウト)。
        "status": status,
        "client": client_label(user_agent, client_app),
    }
    # client は User-Agent との混在で、名乗った呼び出し元かどうか見分けられない。
    # 集計で時刻の突き合わせ (ollama-usage-attribution.py) を要らなくするため、
    # 名乗った値は別欄にも残す。名乗らない呼び出しは従来どおり欄を持たない。
    app = (client_app or "").strip()[:40]
    if app:
        record["client_app"] = app
    for key in ("finish_reason", "response_kind"):
        if usage.get(key):
            record[key] = usage[key]
    if error:
        record["error"] = error[:200]
    target = USAGE_LOG_DIR / f"usage-{now:%Y-%m}.jsonl"
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _usage_lock:
        USAGE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fp:
            fp.write(line)


def json_error(message: str) -> bytes:
    return json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "OllamaOpenWebUIProxy/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/opencode-status":
            self.serve_opencode_status()
            return
        self.forward()

    def do_POST(self) -> None:  # noqa: N802
        self.forward()

    def do_PUT(self) -> None:  # noqa: N802
        self.forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self.forward()

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self.request_allowed():
            return
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         f"Content-Type, {WORKLOAD_HEADER}, X-Client-App")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def request_allowed(self) -> bool:
        client = ipaddress.ip_address(self.client_address[0])
        origin = self.headers.get("Origin", "")
        if not any(client in network for network in ALLOWED_NETWORKS):
            self.send_error(403, "Client network is not allowed")
            return False
        # Open WebUI はコンテナ内のサーバーから接続するため Origin を送らない。
        # 明示したサーバー間ネットワークだけはブラウザ向け CORS 制約の対象外にする。
        if any(client in network for network in TRUSTED_NETWORKS):
            return True
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_error(403, "Origin is not allowed")
            return False
        if not client.is_loopback and not origin:
            self.send_error(403, "Browser origin is required from LAN")
            return False
        browser_routes = {("GET", "/api/tags"), ("POST", "/api/show"), ("POST", "/api/chat"), ("OPTIONS", self.path)}
        if not client.is_loopback and (self.command, self.path) not in browser_routes:
            self.send_error(403, "Route is not allowed from LAN")
            return False
        return True

    def serve_opencode_status(self) -> None:
        """tmux status向け。利用状況メタデータなのでloopbackだけに限定する。"""
        client = ipaddress.ip_address(self.client_address[0])
        if not client.is_loopback:
            self.send_error(403, "Status is only available from loopback")
            return
        payload = json.dumps(_generation_gate.snapshot(), ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def forward(self) -> None:
        if not self.request_allowed():
            return
        body = self.read_body()
        session_key = conversation_key(body)
        target_base_url = TARGET_BASE_URL
        client_app = (self.headers.get("X-Client-App") or "").strip()
        workload = "interactive"
        if self.is_generation_request():
            try:
                body, workload, _model = route_request(
                    body, self.headers.get(WORKLOAD_HEADER) or "", client_app
                )
            except ValueError as exc:
                payload = json_error(str(exc))
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
        measure = self.should_measure()
        started = time.monotonic()
        status = 0
        error = ""
        tail = b""
        gate_ticket = None
        interactive_index = None
        try:
            if self.is_generation_request():
                is_opencode = client_app == OPENCODE_CLIENT_APP
                is_batch_client = workload != "interactive"
                kind = "opencode" if is_opencode else (
                    "background" if is_batch_client else "foreground"
                )
                # background は10分でagingされ必ず次の1件になるため、proxy側では
                # 打ち切らない。その他の未識別対話要求は従来の短いtimeoutを保つ。
                queue_timeout = None if is_batch_client else GENERATION_QUEUE_TIMEOUT
                gate_ticket = _generation_gate.acquire(
                    kind, request_model(body), timeout=queue_timeout
                )
                if gate_ticket is None:
                    status = 429 if is_batch_client else 503
                    error = "generation queue busy"
                    payload = json_error(
                        "Ollama generation queue is busy; retry later")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Retry-After", str(GENERATION_RETRY_AFTER))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if (EVICT_COMPETITORS_ENABLED and is_batch_client
                        and MAX_GENERATIONS == 1):
                    evict_idle_competitors(request_model(body))
            if (workload == "interactive"
                    and request_model(body) == WORKLOAD_MODELS["interactive"]
                    and ROUTE_INTERACTIVE):
                interactive_index = _interactive_router.acquire(
                    session_key, INTERACTIVE_STICKY_WAIT,
                    INTERACTIVE_QUEUE_TIMEOUT,
                )
                if interactive_index is None:
                    status = 503
                    error = "interactive queue busy"
                    payload = json_error(
                        "All interactive Ollama workers are busy; retry later")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Retry-After", str(GENERATION_RETRY_AFTER))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                target_base_url = INTERACTIVE_TARGETS[interactive_index]
            self._generation_ticket = gate_ticket
            request = urllib.request.Request(
                target_base_url + self.path, data=body,
                headers=self.forward_headers(), method=self.command)
            try:
                response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                if interactive_index is None:
                    raise
                failed_index = interactive_index
                _interactive_router.release(failed_index)
                interactive_index = _interactive_router.acquire_other(
                    failed_index, INTERACTIVE_QUEUE_TIMEOUT)
                if interactive_index is None:
                    raise
                target_base_url = INTERACTIVE_TARGETS[interactive_index]
                request = urllib.request.Request(
                    target_base_url + self.path, data=body,
                    headers=self.forward_headers(), method=self.command)
                response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)
            with response:
                status = response.status
                if measure:
                    # identity を要求しても上流が圧縮して返すことはある。
                    # 本文はそのまま流し、計測できなかった理由だけ残す。
                    encoding = (response.headers.get("Content-Encoding") or "").lower()
                    if encoding and encoding != "identity":
                        error = f"unmeasured: content-encoding {encoding}"
                self.send_response(response.status)
                self.copy_response_headers(response.headers.items())
                self.end_headers()
                tail = self.copy_body(response, keep_tail=measure)
        except urllib.error.HTTPError as exc:
            status = exc.code
            error = f"HTTP {exc.code}"
            self.send_response(exc.code)
            self.copy_response_headers(exc.headers.items())
            self.end_headers()
            self.copy_body(exc)
        except urllib.error.URLError as exc:
            error = str(exc.reason)
            payload = json_error(f"Upstream Ollama proxy is unavailable: {exc.reason}")
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:  # noqa: BLE001
            # 依頼元が待たずに切った場合など。応答は返せないが記録は残す。
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            _interactive_router.release(interactive_index)
            if gate_ticket is not None:
                _generation_gate.release(gate_ticket)
            if measure:
                self.record_usage(body, tail, status,
                                  round((time.monotonic() - started) * 1000),
                                  error)

    def read_body(self) -> bytes | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else None

    def forward_headers(self) -> dict[str, str]:
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        # Origin は do_* で検査済み。上流の Ollama は自前の OLLAMA_ORIGINS で
        # 再検査して 403 を返すため渡さない。CORS 応答は proxy が付ける。
        for key in [k for k in headers if k.lower() == "origin"]:
            del headers[key]
        headers["Authorization"] = f"Bearer {OPENWEBUI_API_KEY}"
        headers.setdefault("Accept", "application/json")
        if self.should_measure():
            # 計測する経路だけ非圧縮を要求する。依頼元 (httpx は既定で
            # zstd を要求する) の指定をそのまま通すと上流が圧縮して返し、
            # 控えた末尾が圧縮バイナリになってトークン数を取り出せない。
            for key in [k for k in headers if k.lower() == "accept-encoding"]:
                del headers[key]
            headers["Accept-Encoding"] = "identity"
        return headers

    def copy_response_headers(self, items) -> None:
        for key, value in items:
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower in {"server", "date", "content-length"}:
                continue
            if lower == "access-control-allow-origin":
                continue
            self.send_header(key, value)
        # 上流へは Origin を渡さないので、許可済み origin の CORS は proxy が付ける。
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def copy_body(self, response, keep_tail: bool = False) -> bytes:
        """上流の応答をそのまま流す。keep_tail のときだけ末尾を控える。

        転送は今までどおり読んだそばから書く。控えるのは末尾 USAGE_TAIL_BYTES
        だけなので、長い生成でもメモリは一定に収まる。
        """
        tail = b""
        # HTTPResponse.read(size) は size を満たすかEOFまで待つ。LLMの小さな
        # SSE/NDJSON断片が64KiBに届くまでTUIへ出ないため、read1で現在届いて
        # いる分を即時転送する。BytesIO等のテスト用応答はreadへfallbackする。
        read_available = getattr(response, "read1", response.read)
        while True:
            chunk = read_available(64 * 1024)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
            _generation_gate.received(getattr(self, "_generation_ticket", None))
            if keep_tail:
                tail = (tail + chunk)[-USAGE_TAIL_BYTES:]
        return tail

    def should_measure(self) -> bool:
        return (
            USAGE_LOG_ENABLED
            and self.command == "POST"
            and self.path.split("?", 1)[0] in USAGE_PATHS
        )

    def is_generation_request(self) -> bool:
        return (
            self.command == "POST"
            and self.path.split("?", 1)[0] in GENERATION_PATHS
        )

    def record_usage(self, body: bytes | None, tail: bytes, status: int,
                     elapsed_ms: int, error: str) -> None:
        """使用量を記録する。転送を終えた後 (または諦めた後) に呼ばれる。

        計測は付随的な機能なので、解析や書き込みが何で落ちても proxy 本来の
        転送を巻き込ませない。forward の finally から呼ぶため、ここで送出すると
        本来の例外を差し替えてしまう。原因は journal に残す。
        """
        try:
            client_app = self.headers.get("X-Client-App")
            log_usage(self.path, body, tail, self.headers.get("User-Agent", ""),
                      status, elapsed_ms, error, client_app)
        except Exception as exc:  # noqa: BLE001
            self.log_message("usage log failed: %s", exc)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), fmt % args)
        )


def main() -> None:
    require_config()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)

    def shutdown(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(
        f"Serving Ollama-compatible proxy on http://{LISTEN_HOST}:{LISTEN_PORT} "
        f"-> {TARGET_BASE_URL}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
