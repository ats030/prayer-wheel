#!/usr/bin/env python3
"""opencode が既定にしている ollama モデルを、常時ロードのまま保つ。

なぜ要るか: 裏の ollama (evo-x2) は既定 5分で models をアンロードする。
qwen3-coder-next は 52GB あり、冷えた状態からの初回が十数秒〜数分かかる。
opencode を開くたびにそれを待つのは実用的でない。

なぜこの形か: keep_alive はサーバ側の OLLAMA_KEEP_ALIVE で恒久設定するのが
本筋だが、evo-x2 への SSH 鍵が無い。ollama ネイティブの /api/generate は
keep_alive を受け付け、プロキシがそのまま通すので、こちらから固定できる。
ただし evo-x2 側で ollama が再起動すると固定は消えるため、定期的に叩き直す。

終了コード (~/CLAUDE.md の規約):
  0 = 固定した
  3 = 何もしなかった (対象が無い / 裏側に届かない) — 設計どおり
  1 = 障害 (設定が壊れている、固定を要求したのに反映されない)

3 に「届かない」を含めるのは、15分ごとに走るこのユニットで evo-x2 の停止を
failure にすると、止まっている間ずっと15分おきに通知が飛ぶため。相手が
止まっているのはこのホストの障害ではない。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"
BASE = "http://127.0.0.1:11434"
PROVIDER_PREFIX = "ollama/"
TIMEOUT = 600


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.load(res)


class NoTarget(Exception):
    """固定すべきモデルが無い。設計どおりの結果で、障害ではない。"""


def target_model() -> str:
    """opencode の既定モデル名を返す。

    設定を直に読むのは、既定を切り替えたときにこのスクリプトが勝手に
    追従するため。固定するモデルを二重に持つと必ず食い違う。

    設定が読めない・壊れているのは障害 (例外を投げる)。読めたうえで
    ollama 以外を指しているのは NoTarget = 何もしないのが正しい。
    """
    model = json.loads(CONFIG.read_text(encoding="utf-8")).get("model", "")
    if not model.startswith(PROVIDER_PREFIX):
        raise NoTarget(f"既定モデルが ollama ではない: {model!r}")
    return model[len(PROVIDER_PREFIX):]


def expires_at(model: str) -> str | None:
    try:
        with urllib.request.urlopen(BASE + "/api/ps", timeout=30) as res:
            for entry in json.load(res).get("models", []):
                if entry.get("name") == model:
                    return entry.get("expires_at")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return None


def main() -> int:
    try:
        model = target_model()
    except NoTarget as exc:
        print(exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"opencode の設定を読めない ({CONFIG}): {exc}", file=sys.stderr)
        return 1

    try:
        # プロンプトを省くとロードだけが走る (done_reason: "load")。
        result = post("/api/generate", {"model": model, "keep_alive": -1})
    except urllib.error.URLError as exc:
        # プロキシ未起動、evo-x2 停止、経路断。次回の起動時に拾えばよい。
        print(f"裏側に届かないので何もしない: {exc.reason}", file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"{model} の固定に失敗した: {exc}", file=sys.stderr)
        return 1

    if not result.get("done"):
        print(f"{model} の応答が完了していない: {result}", file=sys.stderr)
        return 1

    until = expires_at(model)
    if until is None:
        print(f"{model} を要求したが /api/ps に現れない", file=sys.stderr)
        return 1

    # keep_alive=-1 は 2318年 のような遠い未来になる。数年先なら固定できている。
    try:
        years = datetime.fromisoformat(until.replace("Z", "+00:00")).year
    except ValueError:
        years = 0
    if years < datetime.now().year + 1:
        print(f"{model} は固定されていない (expires_at={until})", file=sys.stderr)
        return 1

    print(f"{model} を常時ロードに固定した (expires_at={until})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
