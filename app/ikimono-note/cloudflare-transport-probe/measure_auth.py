"""Synthetic existing-format HMAC session CPU; no Google, DB or real cookies."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import time

from measure_remote import collector, HERE

PATHS = ('/health', '/session/out', '/session/in', '/session/tampered', '/session/expired')

def sign(payload, secret):
    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')
    body = b64(json.dumps(payload, separators=(',', ':')).encode())
    return body + '.' + b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secrets-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    secret = json.loads(args.secrets_file.read_text())['IKIMONO_PROBE_SESSION_SECRET']
    valid = sign({'sub': 'synthetic-account', 'email': 'synthetic@example.invalid', 'exp': int(time.time()) + 3600}, secret)
    body, signature = valid.split('.')
    invalid = body + '.' + ('A' if signature[0] != 'A' else 'B') + signature[1:]
    expired = sign({'sub': 'synthetic-account', 'email': 'synthetic@example.invalid', 'exp': 1}, secret)
    cookies = {'/session/in': valid, '/session/tampered': invalid, '/session/expired': expired}
    def factory(path):
        return {'headers': {'Cookie': 'ikimono_session=' + cookies[path]}} if path in cookies else {}
    result = collector.measure(5, origin='https://ikimono-note-transport-preview.ats030.workers.dev',
                               paths=PATHS, request_factory=factory, wrangler_config=HERE / 'remote.jsonc')
    result['session_source_sha256'] = hashlib.sha256((HERE.parent / 'worker_session.mjs').read_bytes()).hexdigest()
    result['remote_wrapper_sha256'] = hashlib.sha256((HERE / 'remote.mjs').read_bytes()).hexdigest()
    for row in [result['subscription_probe'], *result['records']]:
        assert row.get('session_source_sha256') == result['session_source_sha256'], 'Stale session implementation'
        assert row.get('transport_wrapper_sha256') == result['remote_wrapper_sha256'], 'Stale wrapper'
        if row['path'].startswith('/session/'):
            expected = {'available': True, 'reason': '', 'signed_in': row['path'] == '/session/in',
                        'email': 'synthetic@example.invalid' if row['path'] == '/session/in' else None}
            raw = json.dumps(expected, separators=(',', ':')).encode()
            assert row['sha256'] == hashlib.sha256(raw).hexdigest(), 'Session response mismatch'
    result['network_calls'] = 0
    result['scope'] = 'Basic-protected synthetic HMAC session verification; excludes Google OAuth, Python, database, photos, AI and persistence'
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if not result['eligible_for_success_cpu_comparison']:
        raise SystemExit('Incomplete CPU evidence')
    for path in PATHS:
        print(path, [(r['cpu_ms'], r['isolate_invocation']) for r in result['records'] if r['path'] == path])

if __name__ == '__main__':
    main()
