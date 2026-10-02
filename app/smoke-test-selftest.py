#!/usr/bin/env python3
"""smoke-test.py の判定ロジックを合成ページで検証する。

    uv run --project ~ --with playwright python app/smoke-test-selftest.py

なぜ必要か: 初版は本文全体からエラー文字列を探しており、振り返りメモを表示する
daily-reflection を誤検知した (メモに「500だと画面にInternal Server Errorしか
出ない」と書かれていた)。閾値を入れて誤検知を消したが、「鳴らなくなった」ことと
「鳴るべきときに鳴る」ことは別なので、両方向を固定して確認する。

判定を変えるときは必ずこれを通すこと。
"""

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SMOKE = Path(__file__).with_name("smoke-test.py")
FAKE_SERVER = '''
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
BODY = sys.argv[2].encode()
CODE = int(sys.argv[3])
JSON = BODY.startswith(b"{")
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(CODE)
        if JSON:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(BODY)
            return
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<html><head><title>t</title></head><body>" + BODY + b"</body></html>")
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''

# (名前, ポート, 本文, HTTPコード, 検知されるべきか)
CASES = [
    ("本物のエラーページ(短い本文)", 18801, "Internal Server Error", 200, True),
    ("空描画", 18802, "  ", 200, True),
    ("サーバエラー応答", 18803, "エラーです" + "あ" * 100, 500, True),
    ("エラー文字列を含む長い本文", 18804,
     "運用メモ: 500だと画面にInternal Server Errorしか出ない。" + "あ" * 400, 200, False),
    ("正常な画面", 18805, "ダッシュボード" + "い" * 100, 200, False),
    # web-search の / は画面でなく JSON。title も長い本文も無いが正常。
    ("JSON API の正常応答", 18806, '{"ok":true,"site_sources":2}', 200, False),
    ("JSON API のエラー応答", 18807, '{"error":"x"}', 503, True),
]


def load_smoke():
    spec = importlib.util.spec_from_file_location("smoke", SMOKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    smoke = load_smoke()
    server_py = Path("/tmp/smoke-selftest-server.py")
    server_py.write_text(FAKE_SERVER, encoding="utf-8")

    procs = [subprocess.Popen([sys.executable, str(server_py), str(port), body, str(code)])
             for _, port, body, code, _ in CASES]
    time.sleep(2)

    mismatches = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for name, port, _, _, should_fail in CASES:
                problems = smoke.check(browser, "127.0.0.1", {"unit": "selftest", "port": port})
                detected = bool(problems)
                ok = detected == should_fail
                mismatches += 0 if ok else 1
                print(f"{'ok ' if ok else 'NG '}{name:30} "
                      f"期待={'検知' if should_fail else '素通り'} "
                      f"実際={'検知' if detected else '素通り'} {problems[:1]}")
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
        server_py.unlink(missing_ok=True)

    print("\n" + ("全て期待どおり" if mismatches == 0 else f"{mismatches}件が期待と異なる"))
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
