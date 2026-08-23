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
# 前回の送信結果。再生成できるので ~/cache に置く (~/CLAUDE.md「データの保全」)。
# 失われても次回の通知が書き直すだけで、実害は「1回ぶん欠測を伝え損ねる」だけ。
STATE_PATH = Path.home() / "cache" / "backlog-viewer" / "last-send.json"


def webhook_url() -> str:
    env = Path.home() / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


def record_send(ok: bool, day) -> None:
    """送信の結果を残す(失敗は握りつぶす)。連続失敗の回数も持つ。"""
    streak = 0
    if not ok:
        try:
            prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            streak = int(prev.get("streak", 0)) if not prev.get("ok", True) else 0
        except (OSError, ValueError, TypeError):
            streak = 0
        streak += 1
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps({"ok": ok, "date": str(day), "streak": streak}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def missed_note(today) -> str:
    """前回落ちていたら、その事実を伝える一行を返す。

    OnFailure の通知先も同じ Webhook なので、Discord 側の問題では失敗の知らせも
    届かない。復帰したときに本文で伝えるのが唯一の経路になる (ats030-we1i)。
    """
    try:
        prev = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ""
    if prev.get("ok", True):
        return ""
    n = int(prev.get("streak", 1) or 1)
    when = prev.get("date", "不明")
    times = f"{n}回" if n > 1 else "1回"
    return f"⚠ 前回 ({when}) の通知が届かなかった。連続 {times} ぶん欠測している"


def build_message(summary: dict, today, missed: str = "") -> str:
    delta = summary["delta_7d"]
    arrow = f"+{delta}" if delta > 0 else str(delta)
    lines = []
    # 欠測は先頭に置く。埋もれると気づけない。
    if missed:
        lines.append(missed)
    lines += [
        f"**残タスクの週次サマリ ({today:%Y-%m-%d})**",
        f"残 **{summary['remaining']}件** (先週比 {arrow}) / うち外部待ち {summary['deferred']}件",
        f"30日超 {summary['over_30_days']}件 · 滞留の中央値 {summary['median_age']}日",
    ]
    # 凍結は bd defer で伏せるが、bd は期限が来ても自動では戻さない。ここで出さないと
    # 期限切れが永久に埋もれる (2026-08-22 に P1 2件が5〜8日埋もれていた)。
    expired = summary.get("freeze_expired", 0)
    undated = summary.get("freeze_undated", 0)
    if expired or undated:
        parts = []
        if expired:
            parts.append(f"**期限切れの凍結 {expired}件** (見直す)")
        if undated:
            parts.append(f"期限なしの凍結 {undated}件 (期限を入れる)")
        lines.append(" / ".join(parts))
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
    message = build_message(main.weekly_summary(issues, today), today, missed_note(today))
    payload = json.dumps({"content": message}).encode("utf-8")
    # User-Agent は必須。Discord は Python-urllib の既定 UA を 403 で弾く
    # (2026-08-23 実測: UA 無し 403 / UA あり 204)。curl では通るため一時的な障害に
    # 見えていたが、このスクリプトからは一度も届いていなかった (ats030-we1i)。
    req = urllib.request.Request(hook, data=payload, headers={
        "Content-Type": "application/json",
        "User-Agent": "backlog-viewer (https://github.com/ats030, 1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            if res.status >= 300:
                print(f"Discord が {res.status} を返した", file=sys.stderr)
                record_send(False, today)
                return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"Discord への送信に失敗した: {exc}", file=sys.stderr)
        record_send(False, today)
        return 1
    record_send(True, today)
    print(f"送信した: 残 {main.weekly_summary(issues, today)['remaining']}件")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
