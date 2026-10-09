"""Check only the protected synthetic experiment, without AI or user data."""
import base64
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

HERE = Path(__file__).resolve().parent
ORIGIN = "https://ikimono-note-transport-preview.ats030.workers.dev"
state = json.loads(Path('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
credential = "Basic " + base64.b64encode(("preview:" + state["IKIMONO_PREVIEW_PASSWORD"]).encode()).decode()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(path, authenticated=True, extra=None):
    headers = {"Authorization": credential} if authenticated else {}
    headers.update({"User-Agent": "ikimono-transport-check/1.0", **(extra or {})})
    try:
        response = build_opener(NoRedirect).open(Request(ORIGIN + path, headers=headers), timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), response.headers


for path in ('/health', '/payload/1', '/wire/3', '/checked/1', '/payload-checked', '/remote.mjs'):
    assert fetch(path, False)[0] == 401
assert fetch('/health', extra={'Authorization': 'Basic invalid'})[0] == 401
status, body, headers = fetch('/health')
assert status == 200 and json.loads(body)['network_calls'] == 0
assert headers['Cache-Control'] == 'no-store' and 'noindex' in headers['X-Robots-Tag']
assert headers['X-Transport-Source-SHA256'] == hashlib.sha256((HERE / 'worker.mjs').read_bytes()).hexdigest()
assert headers['X-Transport-Wrapper-SHA256'] == hashlib.sha256((HERE / 'remote.mjs').read_bytes()).hexdigest()
assert headers['X-Transport-Native-SHA256'] == hashlib.sha256((HERE.parent / 'worker_transport.mjs').read_bytes()).hexdigest()
assert headers['X-Transport-Template-SHA256'] == hashlib.sha256((HERE / 'fixtures/template.json').read_bytes()).hexdigest()
assert 'X-Preview-Isolate' not in headers
assert 'X-Preview-Isolate' not in fetch('/health', extra={'X-Ikimono-CPU-Probe': 'invalid'})[2]
assert fetch('/payload-checked')[0] == 404 and fetch('/remote.mjs')[0] == 404
assert fetch('/wire/3')[0] == 405
assert fetch('/checked/1')[0] == 405
print('PASS: remote Basic gate, no ordinary runtime IDs, current source SHAs, no source/checked diagnostics')
