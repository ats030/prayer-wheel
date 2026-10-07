"""Readable Discord messages for systemd's shared OnFailure handler."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone


def message(unit: str, description: str, result: str, status: str, log: str,
            timestamp: str) -> str:
    states = {
        "timeout": "制限時間を超えました",
        "exit-code": "処理がエラーを返しました",
        "signal": "シグナルで終了しました",
        "core-dump": "異常終了しました（コアダンプ）",
        "start-limit-hit": "起動失敗が続き、起動回数の上限に達しました",
        "oom-kill": "メモリ不足によって終了しました",
        "resources": "起動に必要な資源を確保できませんでした",
    }
    names = {"backlog-enrich.service": "週次タスク棚卸し",
             "backlog-viewer.service": "残タスク・棚卸し画面",
             "ollama-backlog-pr.service": "タスクの自動PR作成"}
    title = " ".join((names.get(unit) or description or unit).split())[:100]
    title = re.sub(r"([\\`*_~<>\[\]|])", r"\\\1", title)
    # Use a bounded, plain unit name in both display and suggested commands.
    safe_unit = re.sub(r"[^A-Za-z0-9_.@:-]", "_", unit)
    if safe_unit.startswith("-"):
        safe_unit = "_" + safe_unit
    state = states.get(result, "失敗を検出しました（詳細はログを確認してください）")
    detail = f"終了情報：result={result[:50]} / 終了値={status[:20]}"
    if result in {"signal", "core-dump"}:
        detail = f"終了情報：result={result} / signal={status[:20]}"
    head = f"🚨 **処理の失敗：{title}**\n対象：{safe_unit}\n検出日時：{timestamp}\n状態：{state}\n{detail}"
    tail = ("\n**確認するには**\nサーバーで次のコマンドを実行してください。\n"
            f"```sh\nsystemctl --user status {safe_unit} --no-pager\n"
            f"journalctl --user -u {safe_unit} -n 50 --no-pager\n```\n"
            "原因はログで確認してください。")
    excerpt = "\n".join(log.splitlines()[-6:]) or "ログを取得できませんでした。"
    excerpt = re.sub(r"https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/[^\s]+",
                     "[Webhook URLを省略]", excerpt)
    excerpt = excerpt.replace("```", "''' ")
    def size(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    budget = max(0, 1900 - size(head) - size(tail) - 30)
    if size(excerpt) > budget:
        remaining = max(0, budget - 15)
        kept = []
        for char in reversed(excerpt):
            remaining -= size(char)
            if remaining < 0:
                break
            kept.append(char)
        excerpt = "…（前半を省略）\n" + "".join(reversed(kept))
    return f"{head}\n**直近のログ（最大6行）**\n```\n{excerpt}\n```{tail}"


if __name__ == "__main__":
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M 日本時間")
    text = message(*(os.environ.get(key, "") for key in
                     ("UNIT", "DESCRIPTION", "RESULT", "STATUS")),
                   sys.stdin.buffer.read().decode("utf-8", errors="replace"), now)
    print(json.dumps({"content": text, "allowed_mentions": {"parse": []}}, ensure_ascii=False))
