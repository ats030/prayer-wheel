"""Loopback-only echo fixture. Send synthetic data only."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class Echo(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        output = json.dumps({"content_type": self.headers.get("Content-Type"),
                             "body": body.decode("utf-8")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(output)))
        self.end_headers()
        self.wfile.write(output)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8789), Echo).serve_forever()
