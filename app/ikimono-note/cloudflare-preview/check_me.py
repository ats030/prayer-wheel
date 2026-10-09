"""Real session endpoint comparison with actual Python signing; no DB writes."""
import base64
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, build_opener
from check import NoRedirect

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import auth

state = json.loads((Path.home() / '.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
auth.SESSION_SECRET = state['IKIMONO_SESSION_SECRET'].strip()
credential = 'Basic ' + base64.b64encode(('preview:' + state['IKIMONO_PREVIEW_PASSWORD']).encode()).decode()
origin = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8795'
valid = auth.sign_session({'sub': 'http-synthetic-no-db', 'email': '合成@example.invalid', 'exp': int(time.time()) + 600})
cookies = [None, valid, valid + 'x', auth.sign_session({'sub': 'synthetic', 'email': 'expired@example.invalid', 'exp': 1})]
for cookie in cookies:
    session = auth.read_session(cookie)
    expected = {'available': True, 'reason': '', 'signed_in': bool(session), 'email': session.get('email') if session else None}
    headers = {'Authorization': credential, 'User-Agent': 'ikimono-session-http-check/1.0'}
    if cookie:
        headers['Cookie'] = 'ikimono_session=' + cookie
    with build_opener(NoRedirect()).open(Request(origin + '/api/me', headers=headers), timeout=30) as response:
        assert response.status == 200 and json.load(response) == expected
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['X-Robots-Tag'] == 'noindex, nofollow'
        assert 'X-Preview-Isolate' not in response.headers
print('PASS: real JS endpoint matches actual Python session read for signed-out/UTF-8/signed-in/tamper/expiry; no DB or Google request')
