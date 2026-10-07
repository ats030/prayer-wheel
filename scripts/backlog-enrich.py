#!/usr/bin/env python3
"""Weekly enrichment report for the Ollama draft-PR backlog.

Read-only: never runs ``bd close``/``bd defer``/``bd update`` or any git
write. It only reports (a) stale issues with a defer proposal, (b) a draft
acceptance criterion for issues that lack one, and (c) the same gate/score
ranking as ``ollama-backlog-candidates.py``. A human adopts anything with
their own ``bd update`` / config edits.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("/home/ats030")
ENV_PATH = ROOT / ".env"
RESULTS_DIR = ROOT / "data/ollama-backlog"
CONFIG = ROOT / "scripts/ollama-backlog-pr.json"
STALE_DAYS = 14
JST = timezone(timedelta(hours=9))

_spec = importlib.util.spec_from_file_location(
    "ollama_backlog_candidates", Path(__file__).with_name("ollama-backlog-candidates.py"))
candidates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(candidates)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def last_activity(issue: dict) -> str | None:
    stamps = [parse_ts(issue.get(key)) for key in ("started_at", "updated_at", "created_at")]
    valid = [s for s in stamps if s is not None]
    if not valid:
        return None
    return max(valid).isoformat()


def stale_candidates(issues: list[dict], now: datetime | None = None) -> list[dict]:
    """Issues idle for >= STALE_DAYS days, with a defer proposal (text only)."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for issue in issues:
        if issue.get("status") not in ("open", "in_progress"):
            continue
        stamp = [s for s in (parse_ts(issue.get("updated_at")),
                             parse_ts(issue.get("created_at"))) if s]
        if not stamp:
            continue
        idle_days = (now - max(stamp)).days
        if idle_days < STALE_DAYS:
            continue
        rows.append({
            "id": issue["id"],
            "title": issue.get("title", ""),
            "status": issue.get("status"),
            "last_activity": max(stamp).isoformat(),
            "idle_days": idle_days,
            "proposal": (f"bd defer {issue['id']}  # {idle_days}日進捗なし "
                         f"(提案のみ・自動実行しない)"),
        })
    rows.sort(key=lambda row: -row["idle_days"])
    return rows


def draft_acceptance(issue: dict) -> str:
    """Single acceptance-criterion draft from title+description (human edits it)."""
    title = (issue.get("title") or "").strip()
    desc = (issue.get("description") or "").strip()
    first = desc.splitlines()[0].strip() if desc else title
    first = first.strip(";").strip()
    if not first.endswith(("。", ".")):
        first += "であること"
    return f"{first}・ 既存のテストまたは標準コマンドで検証が通ること"


def configured_ids() -> set[str]:
    if CONFIG.is_file():
        return set(json.loads(CONFIG.read_text(encoding="utf-8"))["issues"])
    return set()


def classify(ready: list[dict], with_config: set[str]) -> dict:
    """Same state/gates/score logic as ollama-backlog-candidates.py."""
    ranked, parked, skipped = [], [], []
    for name, issues in candidates.repositories(ready):
        gate = candidates.gates(ROOT / "app" / name)
        repo_ok = (gate["independent"] and gate["github"] and gate["clean"]
                   and gate["base_branch"])
        for issue in issues:
            row = {"id": issue["id"], "title": issue["title"],
                   "priority": issue["priority"], "repo": f"app/{name}",
                   "labels": issue.get("labels") or [],
                   "design": bool(issue.get("design")),
                   "gates": gate}
            if issue["id"] in with_config:
                row["state"] = "already_configured"
                skipped.append(row)
            elif "ollama-draft-pr" in row["labels"]:
                row["state"] = "labeled_not_configured"
                skipped.append(row)
            elif not issue.get("acceptance_criteria"):
                row["state"] = "needs_acceptance"
                parked.append(row)
            elif not repo_ok:
                row["state"] = "repo_gates_fail"
                parked.append(row)
            elif len(issues) > 1:
                row["state"] = "ambiguous_repo"
                parked.append(row)
            else:
                row["state"] = "ready"
                row["score"] = candidates.score(issue, gate)
                ranked.append(row)
    ranked.sort(key=lambda row: (-row["score"], row["priority"], row["id"]))
    return {"ready": ranked, "parked": parked, "skipped": skipped}


def webhook_url() -> str:
    for key in ("BACKLOG_ENRICH_DISCORD_WEBHOOK", "DISCORD_WEBHOOK_URL"):
        value = os.environ.get(key, "").strip().strip('"').strip("'")
        if value:
            return value
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def notify(title: str, body: str) -> None:
    """Best effort: a notification failure must never change the run's outcome."""
    try:
        webhook = webhook_url()
    except (OSError, ValueError) as exc:
        print(f"Discord への通知を省略: .env を読めない ({type(exc).__name__})", file=sys.stderr)
        return
    if not webhook:
        print("Discord への通知を省略: DISCORD_WEBHOOK_URL が未設定", file=sys.stderr)
        return
    payload = json.dumps({"content": (f"**{title}**\n{body}")[:1900],
                          "allowed_mentions": {"parse": []}},
                         ensure_ascii=False).encode()
    try:
        request = urllib.request.Request(webhook, data=payload,
                                         headers={"Content-Type": "application/json",
                                                  "User-Agent": "backlog-enrich/1.0"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"webhook returned {response.status}")
            print(f"Discord 通知成功 (HTTP {response.status})")
    except (RuntimeError, OSError) as exc:
        print(f"Discord への通知に失敗 (http): {exc}", file=sys.stderr)
    except ValueError as exc:
        print(f"Discord への通知に失敗: DISCORD_WEBHOOK_URL の形式が不正 ({type(exc).__name__})",
              file=sys.stderr)


def build_report(ready: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with_config = configured_ids()
    ranking = classify(ready, with_config)
    by_id = {issue["id"]: issue for issue in ready}
    return {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "stale_candidates": stale_candidates(ready, now),
        "missing_acceptance": [
            {"id": row["id"], "title": row["title"], "repo": row["repo"],
             "draft_acceptance": draft_acceptance(by_id[row["id"]])}
            for row in ranking["parked"] if row["state"] == "needs_acceptance"
        ],
        "candidates": ranking,
        "summary": {
            "stale": len(stale_candidates(ready, now)),
            "missing_acceptance": sum(1 for r in ranking["parked"]
                                      if r["state"] == "needs_acceptance"),
            "ready": len(ranking["ready"]),
            "parked": len(ranking["parked"]),
            "skipped": len(ranking["skipped"]),
        },
    }


def notification_body(report: dict) -> str:
    """Explain the weekly report without treating overlapping counts as totals."""
    def unique(rows: list[dict]) -> list[dict]:
        return list({row["id"]: row for row in rows}.values())

    stale = unique(report["stale_candidates"])
    missing = unique(report["missing_acceptance"])
    ranked = {key: unique(rows) for key, rows in report["candidates"].items()}
    s = {"stale": len(stale), "missing_acceptance": len(missing),
         **{key: len(ranked.get(key, [])) for key in ("ready", "parked", "skipped")}}
    lines = [
        "着手可能なタスクを確認しました（全残タスクの集計ではありません）。",
        f"・{STALE_DAYS}日以上動きなし：{s['stale']}件",
        f"・自動PRの検討対象で完了条件の記載なし：{s['missing_acceptance']}件",
        f"・自動PRの候補：{s['ready']}件（実行には承認・設定が必要）",
        f"・自動PRの条件未達：{s['parked']}件／設定済みなどの除外：{s['skipped']}件",
        "※完了条件なしは条件未達の内数です。長期未更新と他の区分にも重複があります。",
    ]
    groups = [
        ("長期未更新 — 続ける・延期する・閉じるを確認", stale),
        ("完了条件なし — 何ができれば完了かを追記", missing),
        ("自動PR候補 — 対象と検証方法を確認", ranked["ready"]),
    ]
    for heading, rows in groups:
        if not rows:
            continue
        lines.extend(["", f"**{heading}**"])
        displayed = 0
        for row in rows[:3]:
            title = " ".join(row["title"].split())
            if len(title) > 60:
                title = title[:59] + "…"
            title = re.sub(r"([\\`*_~<>\[\]|])", r"\\\1", title)
            idle = f"／{row['idle_days']}日未更新" if "idle_days" in row else ""
            entry = f"・{title}（{row['id']}{idle}）"
            # Leave room for later headings, omitted counts, footer and title.
            if len("\n".join(lines + [entry])) > 1400:
                break
            lines.append(entry)
            displayed += 1
        if len(rows) > displayed:
            lines.append(f"ほか{len(rows) - displayed}件")
    lines.extend(["", "確認先：<http://ubuntu-server-app.tailf74832.ts.net:8509/>（Tailnet内）",
                  "今回は集計のみです。タスクの更新・延期・完了処理は行っていません。"])
    return "\n".join(lines)


def main() -> int:
    ready = json.loads(candidates.run(
        ["bd", "ready", "--json", "--limit", "0"]).stdout)
    report = build_report(ready)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(JST).strftime("%Y-%m-%d")
    out_path = RESULTS_DIR / f"enrich-{date}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    s = report["summary"]
    print(f"stale={s['stale']} missing_acceptance={s['missing_acceptance']} "
          f"ready={s['ready']} parked={s['parked']} skipped={s['skipped']}")
    for row in report["stale_candidates"][:5]:
        print(f"  stale: {row['id']} idle={row['idle_days']}d")
    for row in report["missing_acceptance"][:5]:
        print(f"  draft: {row['id']} {row['draft_acceptance'][:80]}")
    for row in report["candidates"]["ready"][:5]:
        print(f"  ready: {row['id']} score={row['score']}")
    print(f"report: {out_path}")

    notify(f"今週のタスク棚卸し｜{date}", notification_body(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
