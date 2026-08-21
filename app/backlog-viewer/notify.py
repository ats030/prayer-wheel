"""残タスクの週次サマリを Discord へ送る。

終了コードは ~/CLAUDE.md の規約に従う。
  0 = 送った / 3 = Webhook 未設定で送らなかった (設計どおり) / 1 = 障害
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import main

URL = "http://ubuntu-server-app:8524/"


def webhook_url() -> str:
    env = Path.home() / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


def build_message(summary: dict, today) -> str:
    delta = summary["delta_7d"]
    arrow = f"+{delta}" if delta > 0 else str(delta)
    lines = [
        f"**残タスクの週次サマリ ({today:%Y-%m-%d})**",
        f"残 **{summary['remaining']}件** (先週比 {arrow}) / うち外部待ち {summary['deferred']}件",
        f"30日超 {summary['over_30_days']}件 · 滞留の中央値 {summary['median_age']}日",
    ]
    if summary["oldest"]:
        lines.append("")
        lines.append("滞留の長い順:")
        for r in summary["oldest"]:
            tag = "[外部待ち] " if r.deferred else ""
            lines.append(f"· {r.age_days}日 P{r.priority} {tag}{r.title[:56]}")
    lines.append("")
    lines.append(f"棚卸し: {URL}")
    return "\n".join(lines)


def main_() -> int:
    hook = webhook_url()
    if not hook:
        print("DISCORD_WEBHOOK_URL が未設定のため通知は送らない", file=sys.stderr)
        return 3
    try:
        issues = main.parse_issues(main.load_raw_issues())
    except Exception as exc:  # noqa: BLE001
        print(f"bd からの取得に失敗した: {exc}", file=sys.stderr)
        return 1
    today = datetime.now(main.JST).date()
    message = build_message(main.weekly_summary(issues, today), today)
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(hook, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            if res.status >= 300:
                print(f"Discord が {res.status} を返した", file=sys.stderr)
                return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"Discord への送信に失敗した: {exc}", file=sys.stderr)
        return 1
    print(f"送信した: 残 {main.weekly_summary(issues, today)['remaining']}件")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
