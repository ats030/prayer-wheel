#!/usr/bin/env python3
"""opencode が既定にしている ollama モデルを、常時ロードのまま保つ。

なぜ要るか: 裏の ollama (evo-x2) は既定 5分で models をアンロードする。
qwen3-coder-next は 52GB あり、冷えた状態からの初回が十数秒〜数分かかる。
opencode を開くたびにそれを待つのは実用的でない。

なぜこの形か: keep_alive はサーバ側の OLLAMA_KEEP_ALIVE で恒久設定するのが
本筋だが、evo-x2 への SSH 鍵が無い。ollama ネイティブの /api/generate は
keep_alive を受け付け、プロキシがそのまま通すので、こちらから固定できる。
ただし evo-x2 側で ollama が再起動すると固定は消えるため、定期的に叩き直す。

keep_alive を渡す先は /api/generate (ネイティブ) だけにすること。
/v1/chat/completions (OpenAI 互換) に keep_alive: -1 を付けると、モデルが即座に
アンロードされる (2026-08-22 実測、/api/ps が空になった)。固定するつもりで逆のことが
起きるので、経路を混ぜないこと。

keep_alive に -1 (恒久) を使わないこと。-1 で固定されたモデルは、VRAM が足りなく
なっても ollama が降ろせなくなり、他のアプリのモデルが一切載らなくなる。
2026-08-31 の実測: 52GB を -1 で固定していた24時間、rss-reader の gemma4:12b 採点は
1582件中 64件しか成功しなかった (4%)。残りは 900秒の上流タイムアウトを待って
503/502 で落ちていた。固定を外した直後の1周回は 67件すべて成功し、中央値 2.3秒。
有限 TTL なら「普段は載っている」を保ちつつ、他所が要求したときは ollama が
LRU で降ろせる。opencode の初回待ちより、他アプリが全滅しないことを優先する。

また keep_alive=-1 は恒久ではない。その後に普通の推論要求が1回来ると既定の 5分 TTL に
戻る (expires が 2318年 から5分後に変わるのを実測)。opencode が使うたびにピンは
外れるので、このユニットは 2分間隔で貼り直す。15分間隔では TTL 5分の谷を埋められず、
52GB の再ロード (実測 約2分) を毎回踏んでいた。

使用中のモデルは蹴らない。qwen3-coder-next (52GB) と qwen3.8:27b (17.7GB) は
VRAM に同居できず、片方を要求するともう片方が降りる。opencode にはクライアント側
タイムアウトが無いため、降ろされた要求は返らず TUI が固まる (2026-08-22 に15分の
実例)。よって別のモデルがロード中なら今回は見送る。ollama は idle 5分で自然に
降ろすので、ピンは次の周回で戻る。

「使用中でない」の判定は /api/ps を二度見る。/api/ps は VRAM の中身しか見えず
待ち行列は見えないため、入れ替えの谷間の数秒を「暇」と誤読すると、他所の生成の
直後に 52GB のロードを割り込ませてしまう (confirm_idle のコメントに実例)。
同じ理由で固定要求は 120秒で打ち切る。長く待つのは順番待ちの証拠でしかない。

終了コード (~/CLAUDE.md の規約):
  0 = TTL を伸ばした / まだ十分温まっている
  3 = 何もしなかった (対象が無い / 裏側に届かない / 別のモデルが使用中 /
      入れ替えの谷間だった / 順番待ちで打ち切った) — 設計どおり
  1 = 障害 (設定が壊れている、固定を要求したのに反映されない)

3 に「届かない」を含めるのは、15分ごとに走るこのユニットで evo-x2 の停止を
failure にすると、止まっている間ずっと15分おきに通知が飛ぶため。相手が
止まっているのはこのホストの障害ではない。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"
BASE = os.environ.get("OLLAMA_KEEPALIVE_BASE", "http://127.0.0.1:11434").rstrip("/")
PROVIDER_PREFIX = "ollama/"
# ロードだけの要求は、GPU が空いていれば 52GB でも十数秒で返る (実測 13.7秒)。
# それ以上待たされるのは順番待ちをしている証拠で、待てば待つほど他所の生成の
# 後ろに 52GB のロードを押し込むことになる。空いていないと分かった時点で降りる。
TIMEOUT = 120

# 貼り直しは 2分間隔なので、TTL は「タイマーが数回落ちても生き残る」程度で足りる。
# 長すぎても意味はない (他所が要求すれば ollama は TTL 内でも降ろす)。
KEEP_ALIVE_SECONDS = 1800

# 残りがこれを切ったら貼り直す。2分間隔の周回を数回ぶん見込む。
RENEW_MARGIN_SECONDS = 600

# /api/ps が空でも「入れ替えの谷間」かもしれないので、少し置いて二度見る。
IDLE_RECHECK_SECONDS = 5


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


def loaded_models() -> dict[str, str] | None:
    """今ロードされているモデルを {名前: expires_at} で返す。届かなければ None。"""
    try:
        with urllib.request.urlopen(BASE + "/api/ps", timeout=30) as res:
            return {
                entry.get("name"): entry.get("expires_at")
                for entry in json.load(res).get("models", [])
                if entry.get("name")
            }
    except (urllib.error.URLError, OSError, ValueError):
        return None


def warm_enough(until: str | None) -> bool:
    """expires_at の残りが RENEW_MARGIN_SECONDS 以上あるか。

    恒久ピン (keep_alive=-1) を使っていた頃は 2318年 のような値だったので
    「数年先か」で判定していた。有限 TTL に変えたので、残り時間で見る。
    """
    if not until:
        return False
    try:
        expires = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (expires - datetime.now(timezone.utc)).total_seconds() >= RENEW_MARGIN_SECONDS


def confirm_idle() -> bool:
    """/api/ps が空なのが本当に暇なのか、入れ替えの谷間なのかを見分ける。

    /api/ps は VRAM に載っているモデルしか見えず、**待ち行列は見えない**。
    ひとつ降ろして次を載せる数秒だけ空になるため、その瞬間を「暇」と読むと
    52GB のロードを他所の要求の直後に割り込ませてしまう。
    2026-08-31 の実例: 12:40:12 と 13:05:12 の2回だけこのすり抜けが起き、
    直後の image-generator の gemma4:31b がそれぞれ 463秒 / 411秒の
    コールドロードを払った (他の周回は正しく見送っていた)。
    """
    time.sleep(IDLE_RECHECK_SECONDS)
    again = loaded_models()
    if again is None:
        print("裏側に届かないので何もしない (/api/ps 再確認)", file=sys.stderr)
        return False
    if again:
        print(
            f"入れ替えの谷間だった。今回は見送る: {', '.join(sorted(again))}",
            file=sys.stderr,
        )
        return False
    return True


def main() -> int:
    try:
        model = target_model()
    except NoTarget as exc:
        print(exc, file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"opencode の設定を読めない ({CONFIG}): {exc}", file=sys.stderr)
        return 1

    # 使用中のモデルを蹴らない。qwen3-coder-next (52GB) と qwen3.8:27b (17.7GB) は
    # 同居できず、片方を要求するともう片方が VRAM から降りる。opencode には
    # クライアント側タイムアウトが無いので、降ろされた要求は返らず TUI が固まる
    # (2026-08-22 に15分の実例)。固定を守ることより使用中を守るほうが優先。
    # ollama は idle 5分で自然に降ろすため、ピンは次の周回で戻る。
    loaded = loaded_models()
    if loaded is None:
        print("裏側に届かないので何もしない (/api/ps)", file=sys.stderr)
        return 3
    if model in loaded:
        if warm_enough(loaded[model]):
            print(f"{model} は載ったままで残りも十分 (expires_at={loaded[model]})")
            return 0
    elif loaded:
        print(
            f"別のモデルが使われているので今回は見送る: {', '.join(sorted(loaded))}",
            file=sys.stderr,
        )
        return 3
    elif not confirm_idle():
        return 3

    try:
        # プロンプトを省くとロードだけが走る (done_reason: "load")。
        result = post(
            "/api/generate", {"model": model, "keep_alive": KEEP_ALIVE_SECONDS}
        )
    except urllib.error.URLError as exc:
        # プロキシ未起動、evo-x2 停止、経路断。次回の起動時に拾えばよい。
        print(f"裏側に届かないので何もしない: {exc.reason}", file=sys.stderr)
        return 3
    except TimeoutError:
        # 順番待ち。障害ではないので failure 通知を出さない (2分後にまた来る)。
        print(
            f"{TIMEOUT}秒で返らないので順番待ちと判断して降りる ({model})",
            file=sys.stderr,
        )
        return 3
    except (OSError, ValueError) as exc:
        print(f"{model} の固定に失敗した: {exc}", file=sys.stderr)
        return 1

    if not result.get("done"):
        print(f"{model} の応答が完了していない: {result}", file=sys.stderr)
        return 1

    after = loaded_models() or {}
    until = after.get(model)
    if until is None:
        print(f"{model} を要求したが /api/ps に現れない", file=sys.stderr)
        return 1
    if not warm_enough(until):
        print(f"{model} の TTL が伸びていない (expires_at={until})", file=sys.stderr)
        return 1

    print(f"{model} を {KEEP_ALIVE_SECONDS}秒ぶん温めた (expires_at={until})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
