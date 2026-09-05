#!/usr/bin/env python3
"""Expose a local Ollama-compatible endpoint backed by Open WebUI."""

from __future__ import annotations

import json
import ipaddress
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
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
REQUEST_TIMEOUT = int(env("OLLAMA_PROXY_TIMEOUT", "600"))
GENERATION_QUEUE_TIMEOUT = float(env("OLLAMA_PROXY_QUEUE_TIMEOUT", "5"))
# X-Client-App を名乗るバッチ要求 (daily-reflection 等) 向けの待機上限。
# opencode の対話要求は応答性を保つため既定の短い GENERATION_QUEUE_TIMEOUT
# のまま。バッチ側は起動時刻がずれて opencode の長時間生成 (実測60秒超) と
# 競合しても、ゲート取得自体で 503 にならないよう長めに確保する (ats030-pe2x)。
GENERATION_QUEUE_TIMEOUT_BATCH = float(env("OLLAMA_PROXY_QUEUE_TIMEOUT_BATCH", "120"))
GENERATION_RETRY_AFTER = int(env("OLLAMA_PROXY_RETRY_AFTER", "30"))
# X-Client-App を名乗るバッチ要求だけ、ゲート取得後に他の常駐モデルを
# keep_alive=0 で退避させる (ats030-pe2x)。_generation_gate は生成要求を
# 1本に絞るため、ここに到達した時点で他の生成要求 (opencodeの対話要求も
# 同じproxyを通る) はこのproxyを通っていない。よって /api/ps に映る
# モデルは使用中ではなく、安全に退避できる。本番で問題が出た場合に
# 再デプロイ無しで切れるよう既定で有効にしておく。
EVICT_COMPETITORS_ENABLED = env("OLLAMA_PROXY_EVICT_COMPETITORS", "1") not in ("0", "false", "no")
EVICT_TIMEOUT = float(env("OLLAMA_PROXY_EVICT_TIMEOUT", "10"))
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
# Ollama は単一 GPU 上で別モデルの要求を内部キューへ積む。依頼元の timeout
# より上流 timeout が長いと、切断済みの生成が何本も残るため proxy の入口で
# 生成系だけを1本に制限する。tags/ps/show 等の管理 API は塞がない。
_generation_gate = threading.Lock()


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
    try:
        request = urllib.request.Request(
            TARGET_BASE_URL + "/api/ps",
            headers={
                "Authorization": f"Bearer {OPENWEBUI_API_KEY}",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=EVICT_TIMEOUT) as response:
            models = json.load(response).get("models") or []
    except Exception:  # noqa: BLE001
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

    def forward(self) -> None:
        if not self.request_allowed():
            return
        target_url = TARGET_BASE_URL + self.path
        body = self.read_body()
        measure = self.should_measure()
        request = urllib.request.Request(
            target_url,
            data=body,
            headers=self.forward_headers(),
            method=self.command,
        )
        started = time.monotonic()
        status = 0
        error = ""
        tail = b""
        gate_acquired = False
        try:
            if self.is_generation_request():
                client_app = self.headers.get("X-Client-App")
                is_batch_client = bool(client_app and client_app.strip())
                # バッチクライアントは opencode の長時間生成 (実測60秒超) と
                # 起動時刻がずれて競合しても、ゲート取得自体で 503 にならない
                # よう長めに待たせる。opencode 側の対話応答性は既定の短い
                # タイムアウトのまま維持する (ats030-pe2x)。
                queue_timeout = (
                    GENERATION_QUEUE_TIMEOUT_BATCH if is_batch_client
                    else GENERATION_QUEUE_TIMEOUT)
                gate_acquired = _generation_gate.acquire(timeout=queue_timeout)
                if not gate_acquired:
                    status = 503
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
                if EVICT_COMPETITORS_ENABLED and is_batch_client:
                    evict_idle_competitors(request_model(body))
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
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
            if gate_acquired:
                _generation_gate.release()
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
            self.send_header(key, value)

    def copy_body(self, response, keep_tail: bool = False) -> bytes:
        """上流の応答をそのまま流す。keep_tail のときだけ末尾を控える。

        転送は今までどおり読んだそばから書く。控えるのは末尾 USAGE_TAIL_BYTES
        だけなので、長い生成でもメモリは一定に収まる。
        """
        tail = b""
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()
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
