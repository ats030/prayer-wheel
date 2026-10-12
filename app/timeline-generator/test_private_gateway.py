from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from private_gateway import allowed_route, make_server, read_gateway_token

TOKEN = "t" * 43


class GatewayTests(unittest.TestCase):
    def test_no_arbitrary_route_or_upstream(self):
        for route in ("https://evil.example/api/jobs", "//evil.example/api/jobs", "/data/private.sqlite3", "/api/jobs?url=https://evil.example", "/api/jobs/1?x=1", "/api/jobs?offset=1&offset=2", "/api/jobs/../quality"):
            self.assertFalse(allowed_route("GET", route), route)
        with self.assertRaises(ValueError):
            make_server(TOKEN, upstream="https://evil.example")
        with self.assertRaises(ValueError):
            make_server("")

    def test_authenticated_forwarding_and_credential_isolation_over_http(self):
        seen = []
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == "/api/health":
                    self.send_response(302)
                    self.send_header("Location", "https://must-not-follow.example")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"private upstream diagnostic must not escape")
            def do_POST(self):
                seen.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps({"id": 1, "result": {"events": [], "trace": {"private": "hidden"}}}).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        origin = f"http://127.0.0.1:{upstream.server_port}"
        gateway = make_server(TOKEN, port=0, upstream=origin)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (upstream, gateway)]
        for thread in threads: thread.start()
        base = f"http://127.0.0.1:{gateway.server_port}"
        def request(path, credential=None, data=None, extras=None):
            headers = {"Content-Type": "application/json", **(extras or {})}
            if credential: headers["Authorization"] = "Bearer " + credential
            req = urllib.request.Request(base + path, headers=headers, data=data)
            try: return urllib.request.urlopen(req, timeout=3)
            except urllib.error.HTTPError as exc: return exc
        try:
            for credential in (None, "wrong"):
                with request("/api/jobs", credential, b'{"query":"test"}') as response:
                    self.assertEqual(response.code, 403)
            with request("/data/private.sqlite3", TOKEN) as response:
                self.assertEqual(response.code, 404)
            with request("/api/jobs", TOKEN, b"x" * 2049) as response:
                self.assertEqual(response.code, 413)
            with request("/api/jobs", TOKEN, extras={"Host": "evil.example"}) as response:
                self.assertEqual(response.code, 403)
            for path in ("/api/health", "/api/quality"):
                with request(path, TOKEN) as response:
                    self.assertEqual(response.code, 502)
                    self.assertNotIn(b"private upstream", response.read())
            with request("/api/jobs", TOKEN, b'{"query":"test"}', {"Cookie": "private=session", "Cf-Access-Jwt-Assertion": "never-forward", "Origin": "https://evil.example"}) as response:
                self.assertEqual(response.code, 201)
                self.assertNotIn("trace", json.load(response)["result"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][1]["Origin"], origin)
            for header in ("Authorization", "Cookie", "Cf-Access-Jwt-Assertion"):
                self.assertNotIn(header, seen[0][1])
        finally:
            for server in (gateway, upstream): server.shutdown(); server.server_close()
            for thread in threads: thread.join(timeout=3)

    def test_private_credential_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text(TOKEN)
            path.chmod(0o600)
            self.assertEqual(read_gateway_token(path), TOKEN)
            path.chmod(0o644)
            with self.assertRaises(ValueError): read_gateway_token(path)
