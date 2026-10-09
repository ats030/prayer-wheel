"""Account real JS session API and unchanged fallback, without AI or DB writes."""
import argparse
import base64
import hashlib
import hmac
import json
from pathlib import Path
import time

from measure_cpu import measure, HERE

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signed-in', action='store_true', help='Use a synthetic subject signed with the existing preview key')
    parser.add_argument('--backend', action='store_true', help='Observe private Python CPU for requests through the real gateway')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.backend and args.signed_in:
        parser.error('Synthetic session cookies are restricted to the JS session API')
    expected = {'available': True, 'reason': '', 'signed_in': args.signed_in,
                'email': 'synthetic@example.invalid' if args.signed_in else None}
    cookie = ''
    if args.signed_in:
        state = json.loads((Path.home() / '.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
        body = encode(json.dumps({'sub': 'cpu-synthetic-no-db', 'email': expected['email'],
                                  'exp': int(time.time()) + 600}, separators=(',', ':')).encode())
        cookie = body + '.' + encode(hmac.new(state['IKIMONO_SESSION_SECRET'].strip().encode(), body.encode(), hashlib.sha256).digest())
    def factory(path):
        # Synthetic login never reaches Python or database routes.
        return {'headers': {'Cookie': 'ikimono_session=' + cookie}} if path == '/api/me' and cookie else {}
    paths = ('/health', '/assets/index.js') if args.backend else ('/api/me', '/health', '/assets/index.js')
    result = measure(5, paths=paths, request_factory=factory,
                     wrangler_config=HERE / ('backend.jsonc' if args.backend else 'front.jsonc'),
                     readiness_path='/health' if args.backend else '/api/me')
    result['scope'] = 'real protected JS /api/me plus existing Python health/assets fallback; excludes actual Google login, database writes, AI and photos'
    result['synthetic_signed_in'] = args.signed_in
    result['cpu_observation_scope'] = 'private Python backend' if args.backend else 'JS gateway'
    result['runtime_observation_scope'] = 'JS gateway; these response counts do not establish Python cold execution'
    manifest = json.loads((HERE / 'edge-manifest.json').read_text())
    expected_digest = manifest['bundle_sha256']
    raw = json.dumps(expected, ensure_ascii=False, separators=(',', ':')).encode()
    for row in [result['subscription_probe'], *result['records']]:
        assert row.get('preview_bundle_sha256') == expected_digest, 'Stale gateway bundle'
        if row['path'] == '/health':
            assert row.get('preview_backend_bundle_sha256') == manifest['python_bundle_sha256'], 'Stale backend bundle'
        if row['path'] == '/api/me':
            assert row['sha256'] == hashlib.sha256(raw).hexdigest(), 'Session status mismatch'
    result['bundle_sha256'] = expected_digest
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    if not result['eligible_for_success_cpu_comparison']:
        raise SystemExit('Incomplete CPU evidence')
    print('readiness', {k: result['subscription_probe'][k] for k in ('cpu_ms', 'isolate_invocation', 'version')})
    for path in paths:
        print(path, [(r['cpu_ms'], r['isolate_invocation']) for r in result['records'] if r['path'] == path])

if __name__ == '__main__':
    main()
