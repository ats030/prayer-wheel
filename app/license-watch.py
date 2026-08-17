#!/usr/bin/env python3
"""許諾レコードの要対応が増えたときだけ Discord へ知らせる。

なぜ必要か: tool-inventory のライセンスタブは画面を開かないと分からない。要対応が
増えるのは、レコードを足したときだけではない。根拠の取得から365日が過ぎれば勝手に
「要確認」へ落ちるし、同じ対象の記録が食い違えば「要対応」になる。どれも静かに起き、
気づくのは次に画面を開いたときになる。

数ではなく名前で比べる。件数が同じでも中身が入れ替わることがあり、そのとき数だけを
見ていると「変化なし」に見えてしまう。

初回は通知しない。状態ファイルが無い時点では全件が「新しく増えたもの」になり、
その一通が今後の通知の信用を削るため。状態だけ保存して終わる。

終了コード (~/CLAUDE.md の規約):
  0 = 増えたものがあり通知した
  3 = 増えていない (設計どおりの「成果物なし」。SuccessExitStatus=3 で success 扱い)
  1 = 障害 (API へ到達できない、応答が壊れている)
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATE_PATH = Path.home() / "cache" / "license-watch" / "state.json"
ENV_PATH = Path.home() / ".env"
API_PORT = 8518
API_TIMEOUT_SEC = 300  # pCloud 上のアプリを走査するため、初回スキャンは数分かかる
DISCORD_LIMIT = 1900  # Discord のメッセージ上限 2000 に対する余裕


def tailnet_ip() -> str:
    """tool-inventory は tailnet IP で待ち受けているので 127.0.0.1 では届かない。"""
    out = subprocess.run(
        ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=20
    )
    ip = out.stdout.strip().splitlines()
    if not ip:
        raise RuntimeError("tailscale の IPv4 アドレスを取得できない")
    return ip[0]


def fetch_records() -> dict:
    url = f"http://{tailnet_ip()}:{API_PORT}/api/licenses"
    with urllib.request.urlopen(url, timeout=API_TIMEOUT_SEC) as resp:
        data = json.load(resp)
    if not isinstance(data.get("records"), list):
        raise RuntimeError("応答に records が無い")
    return data


def snapshot(data: dict) -> dict:
    """比較に使う形へ落とす。表示に必要な最小限だけ持つ。"""
    action = {}
    conflict = {}
    for rec in data["records"]:
        name = rec.get("name", "")
        if rec.get("level") == "action":
            action[name] = " / ".join(rec.get("reasons") or []) or rec.get("status", "")
        if rec.get("conflict_with"):
            conflict[name] = ", ".join(rec["conflict_with"])
    return {"action": action, "conflict": conflict}


def load_state() -> dict | None:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_PATH)


def webhook_url() -> str:
    """秘密は ~/.env にしかない。必要なキーだけ取り出す (notify-failure.sh と同じ)。"""
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_WEBHOOK_URL="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def post_to_discord(text: str) -> None:
    url = webhook_url()
    if not url:
        print("DISCORD_WEBHOOK_URL が未設定のため通知は送らない", file=sys.stderr)
        return
    payload = json.dumps({"content": text[:DISCORD_LIMIT]}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        # 通知が届かなくても、journal には残っているので障害にはしない
        print(f"Discord への送信に失敗した: {exc}", file=sys.stderr)


def format_message(added_action: dict, added_conflict: dict, current: dict) -> str:
    lines = [
        "⚖️ **許諾レコードに手当てが要るものが増えました**",
        f"(いま 要対応 {len(current['action'])} 件 / 食い違い {len(current['conflict'])} 件)",
    ]
    if added_action:
        lines.append("")
        lines.append("**新しく要対応**")
        for name, why in sorted(added_action.items()):
            lines.append(f"・{name} — {why}")
    if added_conflict:
        lines.append("")
        lines.append("**新しく記録が食い違っている**")
        for name, where in sorted(added_conflict.items()):
            lines.append(f"・{name} — {where}")
    return "\n".join(lines)


def main() -> int:
    try:
        data = fetch_records()
    except (urllib.error.URLError, OSError, RuntimeError, ValueError,
            subprocess.SubprocessError) as exc:
        print(f"ライセンス一覧を取得できない: {exc}", file=sys.stderr)
        return 1

    current = snapshot(data)
    previous = load_state()
    save_state(current)

    if previous is None:
        print(
            "初回のため通知しない "
            f"(要対応 {len(current['action'])} 件 / 食い違い {len(current['conflict'])} 件を記録)"
        )
        return 3

    added_action = {k: v for k, v in current["action"].items() if k not in previous.get("action", {})}
    added_conflict = {
        k: v for k, v in current["conflict"].items() if k not in previous.get("conflict", {})
    }
    if not added_action and not added_conflict:
        print(
            "増えていない "
            f"(要対応 {len(current['action'])} 件 / 食い違い {len(current['conflict'])} 件)"
        )
        return 3

    message = format_message(added_action, added_conflict, current)
    # Webhook が未設定でも記録が消えないよう、journal には必ず出す
    print(message)
    post_to_discord(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
