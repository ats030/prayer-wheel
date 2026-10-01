#!/usr/bin/env python3
"""ollama-openwebui-proxy.py の使用量計測が応答を壊さないことを固定する。

    uv run --project ~ python app/ollama-openwebui-proxy-selftest.py

なぜ必要か: この proxy はローカル LLM の全トラフィックが通る唯一の経路で、
落ちると writing / exam-trainer / web-clipper / rss-reader / markdown-generator /
opencode が同時に止まる。計測は「あると嬉しい」程度の付随機能なので、解析が
どう転んでも転送を巻き込んではいけない。よって固定するのは2点。

1. copy_body は今までどおり素通しで、末尾を控えても本文が変わらない
2. 壊れた応答・未知の形式でも record_usage は例外を投げない
3. 上流が失敗しても応答は今までどおり返り、記録だけが1行増える

応答の形は4通りある (native/OpenAI 互換 × ストリーム/非ストリーム)。実際に
2026-08-23 に叩いて採った形をそのまま入れてある。
"""

import importlib.util
import io
import json
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ollama-openwebui-proxy.py"
spec = importlib.util.spec_from_file_location("ollama_proxy", SCRIPT)
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: {got!r} (期待 {want!r})")
        failures.append(name)


class AccessProbe:
    """request_allowed だけを実行するための最小ハンドラ。"""

    request_allowed = proxy.ProxyHandler.request_allowed

    def __init__(self, address, origin="", command="GET", path="/api/tags"):
        self.client_address = (address, 12345)
        self.headers = {"Origin": origin} if origin else {}
        self.command = command
        self.path = path
        self.error = None

    def send_error(self, status, message):
        self.error = (status, message)


print("0. 信頼済みサーバー間ネットワークは Origin なしで通す")
old_allowed, old_trusted = proxy.ALLOWED_NETWORKS, proxy.TRUSTED_NETWORKS
proxy.ALLOWED_NETWORKS = (
    proxy.ipaddress.ip_network("127.0.0.0/8"),
    proxy.ipaddress.ip_network("172.19.0.0/16"),
    proxy.ipaddress.ip_network("192.168.11.0/24"),
)
proxy.TRUSTED_NETWORKS = (
    proxy.ipaddress.ip_network("127.0.0.0/8"),
    proxy.ipaddress.ip_network("172.19.0.0/16"),
)
check("Open WebUI コンテナ", AccessProbe("172.19.0.6").request_allowed(), True)
lan = AccessProbe("192.168.11.13")
check("LAN は Origin なしを拒否", lan.request_allowed(), False)
check("LAN の拒否理由", lan.error, (403, "Browser origin is required from LAN"))
proxy.ALLOWED_NETWORKS, proxy.TRUSTED_NETWORKS = old_allowed, old_trusted


# --- 応答サンプル -----------------------------------------------------------

NDJSON_STREAM = b"".join(
    json.dumps({"model": "qwen3.8:27b", "created_at": "2026-08-23T04:00:0%dZ" % i,
                "response": "x", "done": False}).encode() + b"\n"
    for i in range(5)
) + json.dumps({
    "model": "qwen3.8:27b", "response": "", "done": True, "done_reason": "stop",
    "total_duration": 4_512_000_000, "load_duration": 61_000_000,
    "prompt_eval_count": 137, "eval_count": 402,
}).encode() + b"\n"

NDJSON_SINGLE = json.dumps({
    "model": "qwen3.8:27b", "response": "答え", "done": True,
    "total_duration": 1_200_000_000, "load_duration": 0,
    "prompt_eval_count": 12, "eval_count": 34,
}).encode()

SSE_STREAM = b"".join(
    b"data: " + json.dumps({"id": "c1", "model": "qwen3.8:27b",
                            "choices": [{"delta": {"content": "x"}}]}).encode() + b"\n\n"
    for _ in range(3)
) + b"data: " + json.dumps({
    "id": "c1", "model": "qwen3.8:27b",
    "choices": [{"delta": {"tool_calls": [{"index": 0}]},
                 "finish_reason": "tool_calls"}],
}).encode() + b"\n\n" + b"data: " + json.dumps({
    "id": "c1", "model": "qwen3.8:27b", "choices": [],
    "usage": {"prompt_tokens": 88, "completion_tokens": 210, "total_tokens": 298},
}).encode() + b"\n\ndata: [DONE]\n\n"

# 実応答では 1 チャンクが data 行と空行の 2 行を使うので、行数は出力トークン
# 数の倍近くになる。遡り幅を縮めたときに終了理由から落ちるのを見つけるため、
# 遡り幅を超える長さのストリームを 1 本置いておく。
SSE_LONG = b"".join(
    b"data: " + json.dumps({"id": "c3", "model": "qwen3.8:27b",
                            "choices": [{"delta": {"content": "x"},
                                         "finish_reason": None}]}).encode()
    + b"\n\n" for _ in range(150)
) + b"data: " + json.dumps({
    "id": "c3", "model": "qwen3.8:27b",
    "choices": [{"delta": {}, "finish_reason": "stop"}],
}).encode() + b"\n\ndata: " + json.dumps({
    "id": "c3", "model": "qwen3.8:27b", "choices": [],
    "usage": {"prompt_tokens": 22, "completion_tokens": 132, "total_tokens": 154},
}).encode() + b"\n\ndata: [DONE]\n\n"

OPENAI_SINGLE = json.dumps({
    "id": "c2", "object": "chat.completion", "model": "qwen3.8:27b",
    "choices": [{"message": {"role": "assistant", "content": "hi"}}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
}).encode()

EMBED_RESPONSE = json.dumps({
    "embedding": [0.1] * 8,
}).encode()


print("1. NDJSON ストリームの最終行からトークンを採る")
got = proxy.extract_usage(NDJSON_STREAM)
check("model", got["model"], "qwen3.8:27b")
check("入力", got["input"], 137)
check("出力", got["output"], 402)
check("実行時間 (ms)", got["duration_ms"], 4512)
check("モデル読み込み (ms)", got["load_ms"], 61)

print("2. 非ストリームの本体からも採れる")
got = proxy.extract_usage(NDJSON_SINGLE)
check("入力", got["input"], 12)
check("出力", got["output"], 34)

print("3. SSE の usage 行から採る ([DONE] を跨いで遡る)")
got = proxy.extract_usage(SSE_STREAM)
check("入力", got["input"], 88)
check("出力", got["output"], 210)
check("実行時間は取れない", got["duration_ms"], 0)
check("読み込み時間も取れない", got["load_ms"], 0)
check("終了理由", got["finish_reason"], "tool_calls")
check("応答分類", got["response_kind"], "tool_call")

got = proxy.extract_usage(SSE_LONG)
check("遡り幅より長くても終了理由が採れる", got["finish_reason"], "stop")
check("遡り幅より長くても応答分類が採れる", got["response_kind"], "text")
check("遡り幅より長くても入力が採れる", got["input"], 22)
check("遡り幅より長くても出力が採れる", got["output"], 132)

print("4. OpenAI 互換の非ストリーム")
got = proxy.extract_usage(OPENAI_SINGLE)
check("入力", got["input"], 5)
check("出力", got["output"], 7)

print("5. 埋め込みの応答にトークン数は無い")
check("解析結果", proxy.extract_usage(EMBED_RESPONSE), None)
check("要求からモデルを採る",
      proxy.request_model(b'{"model":"bge-m3","input":"x"}'), "bge-m3")

print("6. 壊れた入力で例外を投げない")
for name, payload in [("空", b""), ("途中で切れた JSON", b'{"prompt_eval_count":'),
                      ("JSON でない", b"<html>502</html>"),
                      ("不正な UTF-8", b"\xff\xfe{\"eval_count\":1}")]:
    try:
        proxy.extract_usage(payload)
        check(name, "例外なし", "例外なし")
    except Exception as exc:  # noqa: BLE001
        check(name, f"{type(exc).__name__}: {exc}", "例外なし")

print("7. copy_body は本文を変えずに末尾だけ控える")


class FakeResponse:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, size):
        return self.stream.read(size)


def copy(data, keep_tail):
    handler = object.__new__(proxy.ProxyHandler)
    handler.wfile = io.BytesIO()
    tail = proxy.ProxyHandler.copy_body(handler, FakeResponse(data), keep_tail=keep_tail)
    return handler.wfile.getvalue(), tail


# 上限を超える長さの生成。頭は捨てられるが、トークン数は最終行にあるので残る。
filler = json.dumps({"model": "qwen3.8:27b", "response": "x" * 40,
                     "done": False}).encode() + b"\n"
big = filler * (proxy.USAGE_TAIL_BYTES // len(filler) + 2000) + NDJSON_SINGLE
sent, tail = copy(big, True)
check("転送した本文", sent, big)
check("控えた長さは上限まで", len(tail), proxy.USAGE_TAIL_BYTES)
check("頭は捨てられている", tail == big, False)
check("末尾からトークンが採れる", proxy.extract_usage(tail)["input"], 12)

sent, tail = copy(big, False)
check("控えないときの転送", sent, big)
check("控えないときは空", tail, b"")

print("8. 計測するのは生成系の POST だけ")


def measure(command, path):
    handler = object.__new__(proxy.ProxyHandler)
    handler.command = command
    handler.path = path
    return proxy.ProxyHandler.should_measure(handler)


check("POST /api/chat", measure("POST", "/api/chat"), True)
check("POST /v1/chat/completions", measure("POST", "/v1/chat/completions"), True)
check("GET /api/tags", measure("GET", "/api/tags"), False)
check("POST /api/show", measure("POST", "/api/show"), False)
check("クエリ付き", measure("POST", "/api/generate?x=1"), True)

print("9. 1リクエスト1行を月次ファイルへ書く")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy.log_usage("/api/chat", b'{"model":"qwen3.8:27b"}', NDJSON_STREAM,
                    "python-requests/2.32.3", 200, 4600)
    proxy.log_usage("/api/embed", b'{"model":"bge-m3"}', EMBED_RESPONSE, "",
                    200, 31)
    files = sorted(proxy.USAGE_LOG_DIR.glob("usage-*.jsonl"))
    check("ファイルは1つ", len(files), 1)
    lines = files[0].read_text(encoding="utf-8").splitlines()
    check("行数", len(lines), 2)
    first = json.loads(lines[0])
    check("path", first["path"], "/api/chat")
    check("model", first["model"], "qwen3.8:27b")
    check("output", first["output"], 402)
    check("client", first["client"], "python-requests")
    check("読み込み時間", first["load_ms"], 61)
    check("proxy 実測", first["elapsed_ms"], 4600)
    check("status", first["status"], 200)
    check("native の終了理由", first["finish_reason"], "stop")
    check("native の応答分類", first["response_kind"], "text")
    check("成功に error は付かない", "error" in first, False)
    second = json.loads(lines[1])
    check("埋め込みのモデル", second["model"], "bge-m3")
    check("埋め込みのトークン", second["output"], 0)
    check("client 不明", second["client"], "unknown")

    print("10. 秘密を記録しない")
    body = files[0].read_text(encoding="utf-8")
    check("Authorization を含まない", "Authorization" in body, False)
    check("Bearer を含まない", "Bearer" in body, False)

print("11. 上流が失敗しても応答は返り、記録は1行増える")


class FakeUpstream(BaseHTTPRequestHandler):
    """本物の Open WebUI の代わり。/api/generate だけ 500 を返す。"""

    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        if self.path.endswith("/api/generate"):
            body = b'{"error":"model requires more system memory"}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        with self.active_lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
        try:
            # 実測所要が 0ms に丸まらない程度に待つ。
            time.sleep(0.05)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(NDJSON_STREAM)))
            self.end_headers()
            self.wfile.write(NDJSON_STREAM)
        finally:
            with self.active_lock:
                type(self).active -= 1

    def log_message(self, *args):
        pass


class StreamingUpstream(BaseHTTPRequestHandler):
    """小さい先頭断片を送り、EOFまで待たずproxyが転送するか検証する。"""

    first = b'{"message":{"content":"first"}}\n'
    second = b'{"done":true}\n'
    pause = 0.35

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write(type(self).first)
        self.wfile.flush()
        time.sleep(type(self).pause)
        self.wfile.write(type(self).second)
        self.wfile.flush()

    def log_message(self, *args):
        pass


def post(base, path, payload):
    request = urllib.request.Request(
        base + path, data=payload, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "selftest/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    upstream, proxy.TARGET_BASE_URL = serve(FakeUpstream)
    front, base = serve(proxy.ProxyHandler)

    status, body = post(base, "/api/chat", b'{"model":"qwen3.8:27b"}')
    check("成功時の応答コード", status, 200)
    check("成功時の本文は素通し", body, NDJSON_STREAM)

    status, body = post(base, "/api/generate", b'{"model":"qwen3-coder-next"}')
    check("上流 500 をそのまま返す", status, 500)
    check("上流の本文もそのまま返す", b"more system memory" in body, True)

    upstream.shutdown()
    upstream.server_close()
    status, body = post(base, "/api/chat", b'{"model":"qwen3.8:27b"}')
    check("上流が居ないと 502", status, 502)
    front.shutdown()
    front.server_close()

    files = sorted(proxy.USAGE_LOG_DIR.glob("usage-*.jsonl"))
    lines = [json.loads(line)
             for line in files[0].read_text(encoding="utf-8").splitlines()]
    check("失敗も含めて3行", len(lines), 3)
    check("成功の status", lines[0]["status"], 200)
    check("成功の実測は 0 に丸まらない", lines[0]["elapsed_ms"] >= 40, True)
    check("500 を記録する", lines[1]["status"], 500)
    check("500 でもモデルは要求から採れる", lines[1]["model"], "qwen3-coder-next")
    check("500 の理由", lines[1]["error"], "HTTP 500")
    check("上流不在は status 0", lines[2]["status"], 0)
    check("上流不在の理由が残る", bool(lines[2].get("error")), True)

print("12. 生成は同時に3本通し、4本目は Retry-After 付き503にする")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy.GENERATION_QUEUE_TIMEOUT = 0.01
    FakeUpstream.max_active = 0
    upstream, proxy.TARGET_BASE_URL = serve(FakeUpstream)
    front, base = serve(proxy.ProxyHandler)
    results = []

    def concurrent_post():
        request = urllib.request.Request(
            base + "/api/chat", data=b'{"model":"qwen3.8:27b"}',
            method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                results.append((response.status, response.headers.get("Retry-After")))
        except urllib.error.HTTPError as exc:
            results.append((exc.code, exc.headers.get("Retry-After")))

    workers = [threading.Thread(target=concurrent_post) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    front.shutdown()
    front.server_close()
    upstream.shutdown()
    upstream.server_close()

    check("応答は成功3件とbusy1件", sorted(code for code, _ in results),
          [200, 200, 200, 503])
    retry_headers = [value for code, value in results if code == 503]
    check("503にRetry-After", retry_headers,
          [str(proxy.GENERATION_RETRY_AFTER)])
    check("上流の最大同時生成数", FakeUpstream.max_active, 3)

print("13. 3枠運用では同時常駐のため別モデルを退避しない")


class EvictionUpstream(BaseHTTPRequestHandler):
    """/api/ps を返し、/api/generate への keep_alive 退避要求を記録する。"""

    resident = []
    generate_calls = []
    ps_fails = False

    def do_GET(self):  # noqa: N802
        if self.path.endswith("/api/ps"):
            if type(self).ps_fails:
                self.send_response(500)
                self.end_headers()
                return
            body = json.dumps({"models": type(self).resident}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length)
        if self.path.endswith("/api/generate"):
            payload = json.loads(raw) if raw else {}
            type(self).generate_calls.append(
                (payload.get("model"), payload.get("keep_alive")))
            body = b'{"done": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(NDJSON_STREAM)))
        self.end_headers()
        self.wfile.write(NDJSON_STREAM)

    def log_message(self, *args):
        pass


def post_with_headers(base, path, payload, headers=None):
    all_headers = {"Content-Type": "application/json", "User-Agent": "selftest/1.0"}
    if headers:
        all_headers.update(headers)
    request = urllib.request.Request(
        base + path, data=payload, method="POST", headers=all_headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    EvictionUpstream.resident = [
        {"name": "qwen3-coder-next:q4_K_M"}, {"name": "qwen3.8:27b"},
    ]
    EvictionUpstream.generate_calls = []
    EvictionUpstream.ps_fails = False
    upstream, proxy.TARGET_BASE_URL = serve(EvictionUpstream)
    front, base = serve(proxy.ProxyHandler)

    status, _ = post_with_headers(base, "/api/chat", b'{"model":"qwen3.8:27b"}',
                                  {"X-Client-App": "daily-reflection"})
    check("X-Client-App付きの応答コード", status, 200)
    check("対象モデル自身は退避しない",
          [c for c in EvictionUpstream.generate_calls if c[0] == "qwen3.8:27b"], [])
    check("別モデルを退避しない", EvictionUpstream.generate_calls, [])

    EvictionUpstream.generate_calls = []
    status, _ = post_with_headers(base, "/api/chat", b'{"model":"qwen3.8:27b"}')
    check("X-Client-App無しの応答コード", status, 200)
    check("X-Client-App無しでは退避しない", EvictionUpstream.generate_calls, [])

    EvictionUpstream.generate_calls = []
    EvictionUpstream.ps_fails = True
    status, _ = post_with_headers(base, "/api/chat", b'{"model":"qwen3.8:27b"}',
                                  {"X-Client-App": "daily-reflection"})
    check("ps失敗時も応答コードは正常", status, 200)
    check("ps失敗時は退避もしない", EvictionUpstream.generate_calls, [])

    front.shutdown()
    front.server_close()
    upstream.shutdown()
    upstream.server_close()

print("14. VRAM予算方式: 既定 (未設定) では常にゲート越しの従来動作")
old_budget = proxy.VRAM_BUDGET_BYTES
proxy.VRAM_BUDGET_BYTES = 0
check("予算未設定はネットワークを叩かず False",
      proxy.admit_without_gate("qwen3.8:27b"), False)

print("15. VRAM予算方式: 既にロード済みのモデルはゲート不要")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy.VRAM_BUDGET_BYTES = 30_000_000_000
    EvictionUpstream.ps_fails = False
    EvictionUpstream.resident = [
        {"name": "qwen3.8:27b", "size_vram": 18_725_795_265},
    ]
    upstream, proxy.TARGET_BASE_URL = serve(EvictionUpstream)
    check("ロード済みモデル宛は True", proxy.admit_without_gate("qwen3.8:27b"), True)
    upstream.shutdown()
    upstream.server_close()

print("16. VRAM予算方式: 未ロードでも合計が予算内なら並行転送を許可")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy._model_size_cache.clear()
    proxy.VRAM_BUDGET_BYTES = 30_000_000_000
    EvictionUpstream.ps_fails = False
    EvictionUpstream.resident = [
        {"name": "qwen3.8:27b", "size_vram": 18_725_795_265},
    ]
    upstream, proxy.TARGET_BASE_URL = serve(EvictionUpstream)
    check("未観測の新モデルはサイズ不明で False (安全側)",
          proxy.admit_without_gate("bge-m3"), False)
    # bge-m3 がロードされた瞬間の /api/ps でサイズがキャッシュへ積まれる。
    EvictionUpstream.resident = [
        {"name": "qwen3.8:27b", "size_vram": 18_725_795_265},
        {"name": "bge-m3", "size_vram": 1_000_000_000},
    ]
    proxy.admit_without_gate("bge-m3")  # 観測してキャッシュへ積むだけの呼び出し
    # bge-m3 がアイドル退避などで /api/ps から消えた後でも、キャッシュ済み
    # サイズを使って合計が予算内かどうかを判定できることを確認する。
    EvictionUpstream.resident = [
        {"name": "qwen3.8:27b", "size_vram": 18_725_795_265},
    ]
    check("再ロード要求は観測済みサイズで予算内なら True",
          proxy.admit_without_gate("bge-m3"), True)
    upstream.shutdown()
    upstream.server_close()

print("17. VRAM予算方式: 合計が予算を超えるならゲートへフォールバック")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy.VRAM_BUDGET_BYTES = 20_000_000_000
    with proxy._model_size_lock:
        proxy._model_size_cache["qwen3-coder-next:q4_K_M"] = 52_000_000_000
    EvictionUpstream.resident = [
        {"name": "qwen3.8:27b", "size_vram": 18_725_795_265},
    ]
    upstream, proxy.TARGET_BASE_URL = serve(EvictionUpstream)
    check("予算超過は False", proxy.admit_without_gate("qwen3-coder-next:q4_K_M"), False)
    upstream.shutdown()
    upstream.server_close()

print("18. VRAM予算方式: /api/ps 失敗時はゲートへフォールバック")
proxy.VRAM_BUDGET_BYTES = 30_000_000_000
with proxy._model_size_lock:
    proxy._model_size_cache["qwen3.8:27b"] = 18_725_795_265
proxy.TARGET_BASE_URL = "http://127.0.0.1:1"  # 接続不可
check("ps不通は False", proxy.admit_without_gate("qwen3.8:27b"), False)

proxy.VRAM_BUDGET_BYTES = old_budget

print("19. VRAM予算方式: 予算内なら並行転送が実際にゲートを介さず通る")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    proxy.VRAM_BUDGET_BYTES = 40_000_000_000
    proxy.GENERATION_QUEUE_TIMEOUT = 0.01
    EvictionUpstream.resident = [{"name": "qwen3.8:27b", "size_vram": 18_725_795_265}]
    EvictionUpstream.generate_calls = []
    upstream, proxy.TARGET_BASE_URL = serve(EvictionUpstream)
    front, base = serve(proxy.ProxyHandler)
    results = []

    def concurrent_post_same_model():
        request = urllib.request.Request(
            base + "/api/chat", data=b'{"model":"qwen3.8:27b"}',
            method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                results.append(response.status)
        except urllib.error.HTTPError as exc:
            results.append(exc.code)

    workers = [threading.Thread(target=concurrent_post_same_model) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    front.shutdown()
    front.server_close()
    upstream.shutdown()
    upstream.server_close()
    check("既にロード済みモデル宛は両方成功 (busyにならない)",
          sorted(results), [200, 200])
proxy.VRAM_BUDGET_BYTES = old_budget

print("20. OpenCode lease中はbackgroundを待たせ、期限後に通す")
old_lease = proxy.OPENCODE_LEASE_SECONDS
old_starvation = proxy.BACKGROUND_STARVATION_SECONDS
proxy.OPENCODE_LEASE_SECONDS = 0.05
proxy.BACKGROUND_STARVATION_SECONDS = 1
scheduler = proxy.GenerationScheduler(max_active=1, max_background=1)
interactive = scheduler.acquire("opencode", "qwen3.8:27b", timeout=1)
scheduler.release(interactive)
background_result = []
worker = threading.Thread(
    target=lambda: background_result.append(
        scheduler.acquire("background", "gemma4:12b", timeout=None)
    )
)
worker.start()
time.sleep(0.02)
check("lease中はbackgroundが待機", background_result, [])
worker.join(timeout=1)
check("lease後にbackgroundが通る", len(background_result), 1)
scheduler.release(background_result[0])

print("21. 10分相当待ったbackgroundはOpenCode待機より先に1件通す")
proxy.OPENCODE_LEASE_SECONDS = 0
proxy.BACKGROUND_STARVATION_SECONDS = 0.05
scheduler = proxy.GenerationScheduler()
blocker = scheduler.acquire("foreground", "busy", timeout=1)
order = []

def acquire_and_record(kind, model):
    ticket = scheduler.acquire(kind, model, timeout=None)
    order.append(kind)
    scheduler.release(ticket)

background = threading.Thread(
    target=acquire_and_record, args=("background", "gemma4:12b"))
background.start()
time.sleep(0.07)
interactive_worker = threading.Thread(
    target=acquire_and_record, args=("opencode", "qwen3.8:27b"))
interactive_worker.start()
time.sleep(0.01)
scheduler.release(blocker)
background.join(timeout=1)
interactive_worker.join(timeout=1)
check("aging済みbackgroundが先", order, ["background", "opencode"])

print("22. 状態には本文を含めず、受信時刻と待機数を返す")
scheduler = proxy.GenerationScheduler()
ticket = scheduler.acquire("opencode", "qwen3.8:27b", timeout=1)
scheduler.received(ticket)
snapshot = scheduler.snapshot()
check("生成状態", snapshot["state"], "generating")
check("モデル", snapshot["model"], "qwen3.8:27b")
check("最終受信", snapshot["last_received_seconds"], 0)
check("本文フィールド無し", "prompt" in snapshot, False)
scheduler.release(ticket)
proxy.OPENCODE_LEASE_SECONDS = old_lease
proxy.BACKGROUND_STARVATION_SECONDS = old_starvation

print("23. 用途別ルーティングはモデルとcontext上限を書き換える")
routed, workload, model = proxy.route_request(
    b'{"model":"auto-batch-light","options":{"num_ctx":99999}}', "", "")
payload = json.loads(routed)
check("light workload", workload, "batch-light")
check("light model", model, "gemma4:12b")
check("batch context", payload["options"]["num_ctx"], 16384)

routed, workload, model = proxy.route_request(
    b'{"model":"auto-batch-light"}', "interactive", "")
payload = json.loads(routed)
check("header優先", workload, "interactive")
check("header優先モデル", model, "qwen3.8:27b")
check("interactive context", payload["options"]["num_ctx"], 65536)

print("24. aging済みバッチがあっても対話1枠を予約する")
old_starvation = proxy.BACKGROUND_STARVATION_SECONDS
proxy.BACKGROUND_STARVATION_SECONDS = 0.01
scheduler = proxy.GenerationScheduler(
    max_active=3, max_background=2, max_background_queue=20)
batch1 = scheduler.acquire("background", "gemma4:12b", timeout=1)
batch2 = scheduler.acquire("background", "gemma4:12b", timeout=1)
waiting_batch = []
worker = threading.Thread(target=lambda: waiting_batch.append(
    scheduler.acquire("background", "gemma4:12b", timeout=1)))
worker.start()
time.sleep(0.02)
interactive = scheduler.acquire("foreground", "qwen3.8:27b", timeout=0.1)
check("aging後も対話が3枠目を取得", interactive is not None, True)
check("3枠が同時active", scheduler.snapshot()["active_count"], 3)
scheduler.release(interactive)
scheduler.release(batch1)
worker.join(timeout=1)
check("解放後に待機バッチが開始", len(waiting_batch), 1)
scheduler.release(waiting_batch[0])
scheduler.release(batch2)
proxy.BACKGROUND_STARVATION_SECONDS = old_starvation

print("25. バッチ待ち行列上限では即時拒否する")
scheduler = proxy.GenerationScheduler(
    max_active=3, max_background=2, max_background_queue=0)
check("queue上限0", scheduler.acquire(
    "background", "gemma4:12b", timeout=None), None)

print("26. 対話routingは会話先頭へstickyで、5秒相当後に空き側へ逃がす")
base_body = json.dumps({"messages": [
    {"role": "system", "content": "rules"},
    {"role": "user", "content": "first"},
]}).encode()
extended_body = json.dumps({"messages": [
    {"role": "system", "content": "rules"},
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "reply"},
]}).encode()
key = proxy.conversation_key(base_body)
check("会話追記後もkey固定", proxy.conversation_key(extended_body), key)
router = proxy.InteractiveRouter(("a", "b"))
preferred = router.acquire(key, sticky_wait=0.03, timeout=0.2)
fallback = []
worker = threading.Thread(target=lambda: fallback.append(
    router.acquire(key, sticky_wait=0.03, timeout=0.2)))
worker.start()
time.sleep(0.01)
check("sticky待ち中は同じworkerを待つ", fallback, [])
worker.join(timeout=0.2)
check("sticky期限後は別worker", fallback, [1 - preferred])
router.release(preferred)
router.release(fallback[0])
router.active = [True, True]
check("両worker busyはtimeout", router.acquire(
    key, sticky_wait=0.01, timeout=0.02), None)
router.active = [False, False]
router.active[preferred] = True
check("障害workerを除外して残存workerへ縮退", router.acquire_other(
    preferred, timeout=0.02), 1 - preferred)
router.release(1 - preferred)

print("27. 小さいストリーム断片をEOF前に依頼元へ転送する")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    upstream, proxy.TARGET_BASE_URL = serve(StreamingUpstream)
    front, base = serve(proxy.ProxyHandler)
    request = urllib.request.Request(
        base + "/api/chat", data=b'{"model":"qwen3.8:27b"}', method="POST",
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=3) as response:
        first_byte = response.read(1)
        first_byte_elapsed = time.monotonic() - started
        remainder = response.read()
    check("先頭byte", first_byte, StreamingUpstream.first[:1])
    check("EOF待ち時間より前に届く",
          first_byte_elapsed < StreamingUpstream.pause - 0.05, True)
    check("本文全体", first_byte + remainder,
          StreamingUpstream.first + StreamingUpstream.second)
    front.shutdown()
    front.server_close()
    upstream.shutdown()
    upstream.server_close()

print("28. 対話先が1つだけでも既定の転送先ではなくそこへ送る")
with tempfile.TemporaryDirectory() as tmp:
    proxy.USAGE_LOG_DIR = Path(tmp) / "ollama-proxy"
    saved = proxy.INTERACTIVE_TARGETS, proxy._interactive_router, proxy.ROUTE_INTERACTIVE

    class MainUpstream(FakeUpstream):
        hits = 0

        def do_POST(self):  # noqa: N802
            type(self).hits += 1
            super().do_POST()

    class WorkerUpstream(MainUpstream):
        hits = 0

    main_server, proxy.TARGET_BASE_URL = serve(MainUpstream)
    worker_server, worker_url = serve(WorkerUpstream)
    proxy.INTERACTIVE_TARGETS = (worker_url,)
    proxy._interactive_router = proxy.InteractiveRouter(proxy.INTERACTIVE_TARGETS)
    proxy.ROUTE_INTERACTIVE = proxy.routes_interactive(
        proxy.INTERACTIVE_TARGETS, proxy.TARGET_BASE_URL)
    front, base = serve(proxy.ProxyHandler)
    try:
        status, _ = post(base, "/api/chat", b'{"model":"qwen3.8:27b"}')
        check("単一対話先の応答コード", status, 200)
        check("単一対話先に届く", WorkerUpstream.hits, 1)
        check("既定の転送先には届かない", MainUpstream.hits, 0)
        check("終了後に対話先を解放", proxy._interactive_router.active, [False])
        check("既定と同じ対話先だけなら振り分けない",
              proxy.routes_interactive(("http://a",), "http://a"), False)
        check("対話先なしなら振り分けない", proxy.routes_interactive((), "http://a"), False)
    finally:
        proxy.INTERACTIVE_TARGETS, proxy._interactive_router, proxy.ROUTE_INTERACTIVE = saved
        for server in (front, main_server, worker_server):
            server.shutdown()
            server.server_close()

print("29. 状態APIはidle/生成中をJSONで返す")
front, base = serve(proxy.ProxyHandler)
try:
    with urllib.request.urlopen(base + "/api/opencode-status", timeout=3) as response:
        idle = json.load(response)
        check("状態APIのContent-Type", response.headers.get_content_type(),
              "application/json")
    check("状態APIのidle", idle["state"], "idle")
    check("状態APIの待機数", idle["queue_depth"], 0)
    check("状態APIの実行数", idle["active_count"], 0)
    ticket = proxy._generation_gate.acquire("opencode", "qwen3.8:27b", timeout=0.1)
    try:
        with urllib.request.urlopen(base + "/api/opencode-status", timeout=3) as response:
            active = json.load(response)
        check("状態APIの生成中", active["state"], "generating")
        check("状態APIの生成数", active["active_count"], 1)
    finally:
        proxy._generation_gate.release(ticket)
finally:
    front.shutdown()
    front.server_close()

print()
if failures:
    print(f"失敗 {len(failures)} 件: {', '.join(failures)}")
    sys.exit(1)
print("全て通過")
