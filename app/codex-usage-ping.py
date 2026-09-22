#!/usr/bin/env python3
"""usage-viewer の Codex タイルを『不明』のまま固定させないための定期 ping。

なぜ要るか: Codex にはライブの使用率 API が無い (`codex doctor` 実測:
auth mode は chatgpt、pay-per-token の API key ではない)。usage-viewer は
~/.codex/sessions 配下のセッションログに埋め込まれた token_count イベントの
rate_limits スナップショットしか読めない (main.py の _parse_codex_file)。
そのため、しばらく codex を手動起動しないと primary(5h)/secondary(7d) の
どちらの窓も resets_at を過ぎ、renderLimits() が意図的に『不明』を出し続ける
(ats030-sg7k でこの『stale なら不明』表示自体は正しい設計と決着済み。
以前は『最後に分かっていた%』を出していたが、外部の実測 (Work アナリティクス)
と食い違うことが分かり不明表示に変えた)。

なぜこの形か (grill-me審査 option b、2026-09-21): 表示ロジックを直すべき
バグは無く、あるのは「データが古すぎる」という運用上のギャップだけ。
最小の可逆な実験として、codex exec で軽量なダミーセッションを定期的に
打ち、rate_limits を新鮮なまま保つ。これは Codex のplan別レート制限枠を
実際に消費する運用コミットメントであり (課金ではなくクォータ消費)、
効果とコストが見合うかは要経過観察 (ats030-qxb3)。

なぜ毎回打たないか: primary窓は5時間あるので、手動で codex を使っていれば
ping は不要。既存データの resets_at が未来ならまだ新鮮と判断してスキップし、
クォータを消費しない。過去なら (=次に見るユーザーに『不明』を見せてしまう
前に) 軽量セッションを1本流して rate_limits を更新する。

なぜ専用スクラッチディレクトリか: $HOME で実行すると AGENTS.md/CLAUDE.md や
session_start フックの分だけ毎回コンテキストが膨らむ。~/cache/codex-ping は
中身が空で再生成可能 (CLAUDE.md の運用方針: 再生成可能なものは ~/cache)。
--sandbox read-only + -a never + --skip-git-repo-check で承認待ちも
ファイル書き込みも発生させない。

終了コード (~/CLAUDE.md の規約):
  0 = ping を打って rate_limits を更新した
  3 = 既存データがまだ新鮮なので何もしなかった (設計どおり)
  1 = 障害 (codex 呼び出し失敗、更新されたはずのデータが確認できない)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

CODEX_SESSIONS = Path.home() / ".codex" / "sessions"
SCRATCH_DIR = Path.home() / "cache" / "codex-ping"
LIMIT_ID = "codex"
PROMPT = "OK とだけ返答してください。"
TIMEOUT_SECONDS = 170

# 直近何ファイルまで遡って rate_limits を探すか。最新ファイルにイベントが
# 無い (即エラー終了した等) 場合に備えた保険で、通常は1ファイル目で見つかる。
SCAN_FILES = 5


def _rate_limits_in_file(path: Path) -> dict | None:
    """1つの rollout ファイルから最後の rate_limits スナップショットを取り出す。"""
    found = None
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                payload = event.get("payload", {})
                if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits")
                if rate_limits and rate_limits.get("limit_id") == LIMIT_ID:
                    found = rate_limits
    except OSError:
        return None
    return found


def latest_rate_limits() -> dict | None:
    """全セッションログの中から最新の rate_limits スナップショットを返す。"""
    files = sorted(
        CODEX_SESSIONS.glob("*/*/*/rollout-*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files[:SCAN_FILES]:
        rate_limits = _rate_limits_in_file(path)
        if rate_limits:
            return rate_limits
    return None


def is_fresh(rate_limits: dict | None) -> bool:
    """primary 窓の resets_at がまだ未来なら『新鮮』とみなす。"""
    if not rate_limits:
        return False
    primary = rate_limits.get("primary")
    if not primary or not primary.get("resets_at"):
        return False
    return primary["resets_at"] > time.time()


def run_ping() -> tuple[bool, str]:
    """軽量な codex exec を1本走らせる。(成功したか, ログ用メッセージ)"""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "codex", "-a", "never", "exec",
        "-C", str(SCRATCH_DIR),
        "--skip-git-repo-check",
        "--sandbox", "read-only",
        "--json",
        PROMPT,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "codex コマンドが見つからない"
    except subprocess.TimeoutExpired:
        return False, f"{TIMEOUT_SECONDS}秒で応答が返らない"

    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-5:]
        return False, f"codex exec が exit={result.returncode}: {' / '.join(tail)}"

    usage = ""
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "turn.completed":
            usage = json.dumps(event.get("usage", {}), ensure_ascii=False)
    return True, f"codex exec 完了 usage={usage}"


def main() -> int:
    before = latest_rate_limits()
    if is_fresh(before):
        primary = before["primary"]
        print(
            f"既存の rate_limits がまだ新鮮 (primary resets_at={primary['resets_at']})。"
            " ping しない",
        )
        return 3

    ok, message = run_ping()
    print(message, file=sys.stderr if not ok else sys.stdout)
    if not ok:
        return 1

    after = latest_rate_limits()
    if not is_fresh(after):
        print(
            f"ping後もrate_limitsが新鮮にならない (取得結果: {after})",
            file=sys.stderr,
        )
        return 1

    print(f"rate_limits を更新した (primary resets_at={after['primary']['resets_at']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
