#!/usr/bin/env python3
"""ollama-keepalive.py が「使用中のモデルを蹴らない」ことを固定する。

    uv run --project ~ python app/ollama-keepalive-selftest.py

なぜ必要か: 初版は /api/ps を見ずに毎回 /api/generate を keep_alive=-1 で投げて
いた。ロード済みかを確認しないため、設定の model 以外を使っていると15分以内に
必ず追い出される。opencode にはクライアント側タイムアウトが無く、追い出された
要求は返らないので TUI が固まる (2026-08-22 に15分の実例)。

qwen3-coder-next (52GB) と qwen3.8:27b (17.7GB) は同居できない。片方を要求すると
もう片方が VRAM から降りる。よって「固定を守る」より「使用中を蹴らない」を優先する。
ollama は idle 5分で自然に降ろすので、ピンは次の周回で戻る。
"""

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ollama-keepalive.py"
spec = importlib.util.spec_from_file_location("keepalive", SCRIPT)
ka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ka)

FAR = "2318-12-02T12:39:05.129815026Z"
SOON = "2026-08-22T13:30:00.000000000Z"
TARGET = "qwen3-coder-next:latest"
OTHER = "qwen3.8:27b"

failures = []


def check(name, got, want):
    if got == want:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}: {got!r} (期待 {want!r})")
        failures.append(name)


def run(loaded_sequence, *, target=TARGET):
    """loaded_models() の戻り値を順に返しながら main() を回し、(rc, post回数) を返す。"""
    calls = []
    seq = list(loaded_sequence)

    ka.target_model = lambda: target
    ka.loaded_models = lambda: seq.pop(0) if seq else (seq[-1] if seq else None)
    ka.post = lambda path, payload: calls.append((path, payload)) or {"done": True}
    ka.time.sleep = lambda seconds: None
    rc = ka.main()
    return rc, len(calls)


print("1. 目的のモデルが固定済みなら何もしない")
rc, calls = run([{TARGET: FAR}])
check("終了コード", rc, 0)
check("post を呼ばない", calls, 0)

print("2. 別のモデルが載っているなら見送る (蹴らない)")
rc, calls = run([{OTHER: SOON}])
check("終了コード", rc, 3)
check("post を呼ばない", calls, 0)

print("3. 何も載っていないなら固定する")
rc, calls = run([{}, {}, {TARGET: FAR}])
check("終了コード", rc, 0)
check("post を1回呼ぶ", calls, 1)

print("4. 再確認で別のモデルが現れたら見送る")
rc, calls = run([{}, {OTHER: SOON}])
check("終了コード", rc, 3)
check("post を呼ばない", calls, 0)

print("5. 目的のモデルが載っているが未固定なら固定し直す (蹴らない)")
rc, calls = run([{TARGET: SOON}, {TARGET: FAR}])
check("終了コード", rc, 0)
check("post を1回呼ぶ", calls, 1)

print("6. /api/ps に届かないなら何もしない")
rc, calls = run([None])
check("終了コード", rc, 3)
check("post を呼ばない", calls, 0)

print("7. 固定を要求したのに反映されないのは障害")
rc, calls = run([{}, {}, {}])
check("終了コード", rc, 1)

print("8. 別のモデルと目的のモデルが両方載っているなら固定してよい")
rc, calls = run([{TARGET: SOON, OTHER: SOON}, {TARGET: FAR, OTHER: SOON}])
check("終了コード", rc, 0)
check("post を1回呼ぶ", calls, 1)

print()
if failures:
    print(f"失敗 {len(failures)} 件: {', '.join(failures)}")
    sys.exit(1)
print("全て通過")
