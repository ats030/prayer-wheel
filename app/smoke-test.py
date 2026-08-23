#!/usr/bin/env python3
"""稼働中のWebアプリを実ブラウザで開き、画面が壊れていないかを確認する。

なぜHTTPチェックでは足りないか: 2026-08-02 に app-portal が HTTP 200 を返したまま
一覧を描画できない状態になった (/api/status が KeyError で 500、画面は空)。
ポート監視も systemd の OnFailure も、プロセスは生きているため何も検知しなかった。
サーバが起動していることと、画面が使えることは別の問題である。

判定 (どれか一つでも該当したら失敗):
  - HTTP ステータスが 2xx でない
  - <title> が空
  - 本文が MIN_BODY_CHARS 未満 (空描画)。実測の最小は image-editor の74文字
  - コンソールに error が出ている
  - 同一オリジンへのリクエストが 5xx を返した ← app-portal の事例はこれで捕まる
  - 本文が短く、かつトレースバックやサーバエラーの文字列だけが出ている

文字列一致は本文が短いときにしか使わない。任意のテキストを表示するアプリでは
本文にエラー文字列が普通に現れる (初版は daily-reflection の振り返りメモを誤検知した)。

対象は systemd ユニットの Description "(port NNNN)" から拾う。app-portal が
一覧を作るのと同じ出所なので、サービスを足せば自動で対象に入る。

終了コード: 0=全て正常 / 1=壊れている画面がある (~/CLAUDE.md の規約に従う)
"""

import re
import subprocess
import time
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

UNIT_DIR = Path.home() / ".config/systemd/user"
PORT_RE = re.compile(r"port\s*(\d{4,5})", re.I)
MIN_BODY_CHARS = 40
# エラーページ判定に使う本文長の上限。これを超える本文は「中身のある画面」とみなし、
# エラー文字列が含まれていても内容として扱う (下の ERROR_MARKERS の注記を参照)
ERROR_PAGE_MAX_CHARS = 300
NAV_TIMEOUT_MS = 20000
# 全ホストで落ちたときに待つ秒数。瞬間的な負荷なら空く。
RETRY_WAIT_SEC = 5
ERROR_MARKERS = (
    "Traceback (most recent call last)",
    "Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
)


def tailnet_ip() -> str | None:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=10).stdout.split()
        return out[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def is_enabled(unit: str) -> bool:
    """systemd で有効になっているか。無効なものは監視しない。

    凍結したアプリ (使わないと決めて disable したもの) を叩き続けると、接続失敗が
    通知になり issue になる。「見ないと決めたものが通知を出す」のは矛盾なので、
    disable を監視対象外の意思表示として扱う (2026-08-22)。

    判定できないときは True を返す。監視から漏らすより、鳴らしすぎるほうが安全。
    """
    try:
        out = subprocess.run(["systemctl", "--user", "is-enabled", unit],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return True
    return out.stdout.strip() not in ("disabled", "masked")


def discover_targets() -> list[dict]:
    targets = []
    for f in sorted(UNIT_DIR.glob("*.service")):
        # テンプレートユニットは起動対象ではない
        if f.name.endswith("@.service"):
            continue
        if not is_enabled(f.name):
            continue
        try:
            desc = next((l.split("=", 1)[1].strip() for l in f.read_text(encoding="utf-8").splitlines()
                         if l.startswith("Description=")), "")
        except OSError:
            continue
        m = PORT_RE.search(desc)
        if m:
            targets.append({"unit": f.stem, "port": int(m.group(1))})
    return targets


def check(browser, host: str, target: dict) -> list[str]:
    """失敗理由のリストを返す。空なら正常。到達できなければ None 相当の例外を投げる。"""
    console_errors: list[str] = []
    server_errors: list[str] = []
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.on("console", lambda m: console_errors.append(m.text[:100]) if m.type == "error" else None)
    page.on("response", lambda r: server_errors.append(f"{r.status} {r.url.split('/', 3)[-1][:50]}")
            if r.status >= 500 and f":{target['port']}" in r.url else None)
    try:
        resp = page.goto(f"http://{host}:{target['port']}/",
                         wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        # JS で描画するアプリがあるため、fetch が落ち着くまで待つ
        page.wait_for_load_state("networkidle", timeout=NAV_TIMEOUT_MS)
        problems = []
        if resp is None or not (200 <= resp.status < 300):
            problems.append(f"HTTP {resp.status if resp else '応答なし'}")
        if not page.title().strip():
            problems.append("titleが空")
        body = page.inner_text("body").strip()
        if len(body) < MIN_BODY_CHARS:
            problems.append(f"本文が{len(body)}文字しかない")
        # エラー文字列は「本文がそれだけ」のときにしか判定に使えない。本文全体を
        # 対象にしたら daily-reflection を誤検知した —— 振り返りメモを表示する
        # アプリで、メモ本文に「500だと画面にInternal Server Errorしか出ない」と
        # 書かれていた。任意のテキストを表示するアプリでは文字列一致は成立しない。
        # 実際のエラーページは短い (Starlette の 500 応答は本文 "Internal Server Error"
        # の21文字)。長い本文中の言及は、下のコンソールerrorと5xx応答の判定に任せる。
        if len(body) < ERROR_PAGE_MAX_CHARS:
            for marker in ERROR_MARKERS:
                if marker in body:
                    problems.append(f"本文にエラー表示: {marker}")
                    break
        if console_errors:
            problems.append(f"コンソールerror: {console_errors[0]}")
        if server_errors:
            problems.append(f"サーバエラー応答: {server_errors[0]}")
        return problems
    finally:
        context.close()


def main() -> int:
    targets = discover_targets()
    if not targets:
        print("対象のサービスが見つからない", file=sys.stderr)
        return 1

    hosts = ["127.0.0.1"]
    ip = tailnet_ip()
    if ip:
        hosts.append(ip)  # tailnet IP にしか bind しないサービスがある

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for t in targets:
            last_error = None
            # 全ホストで落ちたら一度だけやり直す。1回のタイムアウトで通知を飛ばすと
            # 誤報になる。2026-08-23 02:45 に web-clipper が TimeoutError で NG に
            # なったが、同じ2分間にアプリ側は23リクエストを正常に処理しており、
            # 再実行では 18/18 正常だった。落ちていたのはブラウザ側。
            # ~/CLAUDE.md の「狼少年にしない」に従い、確度を上げてから鳴らす。
            for attempt in (1, 2):
                for host in hosts:
                    try:
                        problems = check(browser, host, t)
                    except Exception as exc:  # 到達不能。次のホストを試す
                        last_error = f"{type(exc).__name__}"
                        continue
                    if problems:
                        failures.append(f"{t['unit']} (port {t['port']}): " + " / ".join(problems))
                        print(f"NG  {t['unit']:22} {' / '.join(problems)}")
                    else:
                        note = " (再試行で成功)" if attempt == 2 else ""
                        print(f"ok  {t['unit']:22} port={t['port']} host={host}{note}")
                    break
                else:
                    if attempt == 1:
                        time.sleep(RETRY_WAIT_SEC)
                        continue
                    failures.append(f"{t['unit']} (port {t['port']}): どのホストからも開けない ({last_error})")
                    print(f"NG  {t['unit']:22} どのホストからも開けない ({last_error})")
                break
        browser.close()

    print(f"\n{len(targets) - len(failures)}/{len(targets)} 正常")
    if failures:
        print("\n壊れている画面:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
