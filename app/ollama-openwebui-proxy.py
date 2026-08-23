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
ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(value.strip())
    for value in env("OLLAMA_PROXY_ALLOWED_NETWORKS", "127.0.0.0/8").split(",")
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
USAGE_PATHS = frozenset({
    "/api/generate", "/api/chat", "/api/embed", "/api/embeddings",
    "/v1/chat/completions", "/v1/completions", "/v1/embeddings",
})
_usage_lock = threading.Lock()


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


def extract_usage(payload: bytes) -> dict | None:
    """応答の末尾からトークン数を取り出す。取れなければ None。

    4通りある。NDJSON ストリーム (Ollama native) / SSE ストリーム (OpenAI 互換) /
    それぞれの非ストリーム。いずれも欲しい値は末尾にあるので、後ろから見る。
    """
    if not payload:
        return None
    lines = payload.split(b"\n")
    for raw in reversed(lines[-200:]):
        line = raw.strip()
        if line.startswith(b"data:"):
            line = line[5:].strip()
        if not line.startswith(b"{"):
            continue
        try:
            found = _usage_from_object(json.loads(line))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            continue
        if found:
            return found
    # 非ストリームで本文に改行が入っている (整形済み JSON) 場合の保険。
    try:
        return _usage_from_object(json.loads(payload))
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


def client_label(user_agent: str) -> str:
    """User-Agent を呼び出し元の目印に縮める。

    どのアプリかまでは分からない (自作アプリは大半が Python-urllib のまま)。
    アプリの区別はモデル名の方が当てになるので、これは補助として置く。
    """
    ua = (user_agent or "").strip()
    if not ua:
        return "unknown"
    head = ua.split()[0].split("/")[0].strip()
    return head[:40] or "unknown"


def log_usage(path: str, request_body: bytes | None, tail: bytes,
              user_agent: str, status: int, elapsed_ms: int,
              error: str = "") -> None:
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
        "client": client_label(user_agent),
    }
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
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                status = response.status
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

    def record_usage(self, body: bytes | None, tail: bytes, status: int,
                     elapsed_ms: int, error: str) -> None:
        """使用量を記録する。転送を終えた後 (または諦めた後) に呼ばれる。

        計測は付随的な機能なので、解析や書き込みが何で落ちても proxy 本来の
        転送を巻き込ませない。forward の finally から呼ぶため、ここで送出すると
        本来の例外を差し替えてしまう。原因は journal に残す。
        """
        try:
            log_usage(self.path, body, tail, self.headers.get("User-Agent", ""),
                      status, elapsed_ms, error)
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
