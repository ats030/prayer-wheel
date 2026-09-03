#!/usr/bin/env python3
"""visit-log 代理計測プロキシ (設定ファイル駆動、複数サイト対応)。

HTML編集ができないサードパーティ製 Web サービスの手前に立つ透過プロキシ。
リクエストは無加工でそのまま target_base へ中継し、レスポンスを返し終えた後に
別スレッドで visit-log の px.gif へビーコンを送る。ビーコン送信の失敗・遅延が
対象サービスへの応答を一切ブロックしないことが前提 (daemon thread + 短timeout)。

設定は ~/.config/visit-log-proxy/sites.json。1 サイト = 1 リスンポート。
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "visit-log-proxy" / "sites.json"


def fire_beacon(visit_log_base: str, site_name: str, client_ip: str, path: str, referer: str) -> None:
    qs = urllib.parse.urlencode({"s": site_name, "p": path, "r": referer})
    req = urllib.request.Request(f"{visit_log_base}/px.gif?{qs}")
    req.add_header("X-Forwarded-For", client_ip)
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception as exc:  # noqa: BLE001 ビーコン失敗は対象サービスに影響させない
        print(f"[beacon:{site_name}] failed: {exc}", file=sys.stderr)


def make_handler(site_name: str, target_base: str, visit_log_base: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _proxy(self) -> None:
            length = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(length) if length else None

            req = urllib.request.Request(target_base + self.path, data=body, method=self.command)
            for key, value in self.headers.items():
                if key.lower() in ("host", "content-length"):
                    continue
                req.add_header(key, value)

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.send_response(resp.status)
                    for key, value in resp.getheaders():
                        if key.lower() in ("connection", "transfer-encoding"):
                            continue
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except urllib.error.HTTPError as exc:
                self.send_response(exc.code)
                self.end_headers()
                self.wfile.write(exc.read())
                return

            referer = self.headers.get("referer", "")
            client_ip = self.client_address[0]
            threading.Thread(
                target=fire_beacon,
                args=(visit_log_base, site_name, client_ip, self.path, referer),
                daemon=True,
            ).start()

        def do_GET(self) -> None:  # noqa: N802
            self._proxy()

        def do_POST(self) -> None:  # noqa: N802
            self._proxy()

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[proxy:{site_name}] {self.address_string()} - {fmt % args}")

    return Handler


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    visit_log_base = config["visit_log_base"]
    sites = config["sites"]
    if not sites:
        print("sites.json に有効なサイト定義がありません", file=sys.stderr)
        sys.exit(1)

    servers = []
    for site in sites:
        handler = make_handler(site["name"], site["target_base"], visit_log_base)
        server = ThreadingHTTPServer((site["listen_host"], site["listen_port"]), handler)
        servers.append(server)
        print(
            f"[{site['name']}] listening on http://{site['listen_host']}:{site['listen_port']}"
            f" -> {site['target_base']} (beacon: {visit_log_base}/px.gif?s={site['name']})"
        )

    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers[1:]]
    for t in threads:
        t.start()
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
