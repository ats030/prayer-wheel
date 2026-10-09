"""Local native-module boundary check; every input fails before provider HTTP."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import httpx

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import config_store

def check(origin="http://localhost:8795", enabled=True):
    assert urlsplit(origin).hostname in {"localhost", "127.0.0.1"}, "Local checks only"
    secrets = json.loads(Path('/home/ats030/.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')
    body = encode(json.dumps({"sub": "synthetic-native-boundary-check", "email": "synthetic@example.invalid", "exp": int(time.time()) + 300}).encode())
    cookie = body + "." + encode(hmac.new(secrets['IKIMONO_SESSION_SECRET'].encode(), body.encode(), hashlib.sha256).digest())
    reports = json.dumps([{"metadata": {}, "measured": {"width": 600, "height": 450, "pixels": 270000,
        "brightness": 120, "sharpness": 200, "contrast": 30}}])
    model = config_store.MODELS['gemini'][0]['id']
    fields = {"request_provider": "gemini", "request_model": model, "request_api_key": "synthetic-never-forward",
        "client_photos": reports}
    with httpx.Client(base_url=origin, auth=('preview', secrets['IKIMONO_PREVIEW_PASSWORD']),
                      cookies={'ikimono_session': cookie}, timeout=30) as client:
        response = client.post('/api/provider/template', json={"model": model, "count": 1, "client_photos": reports})
        assert response.status_code == (200 if enabled else 404), (response.status_code, response.text[:200])
        assert client.get('/api/settings').json()['native_transport'] is enabled
        for raw in (b'{}', b'not-json', b'{"contents": []}'):
            response = client.post('/identify', data=fields,
                files={'provider_payload': ('provider.json', raw, 'application/json')})
            assert response.status_code == 400, (response.status_code, response.text[:200])
        response = client.post('/identify', data=fields,
            files={'provider_payload': ('provider.json', b'{}', 'text/plain')})
        assert response.status_code == 400
        client.cookies.clear()
        response = client.post('/api/provider/template', json={"model": model, "count": 1, "client_photos": reports})
        assert response.status_code == 401
    print('PASS: local native transport ' + ('ON' if enabled else 'OFF') + ', template gate, invalid payload rejection, login gate; no provider HTTP')

if __name__ == '__main__':
    check(enabled='--off' not in sys.argv)
