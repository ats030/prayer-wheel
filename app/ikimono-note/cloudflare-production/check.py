"""Read-only checks of the protected production candidate and migrated shares."""
import importlib.util
import json
import hmac
from pathlib import Path
import sys
from urllib.request import Request, build_opener

HERE=Path(__file__).resolve().parent
PREVIEW=HERE.parent/'cloudflare-preview'
STATE=Path('/var/tmp/ikimono-cloudflare-production-private/secrets.json')
ORIGIN='https://ikimono-note.ats030.workers.dev'
STAGE='initialization'
sys.path.insert(0,str(HERE.parent/'cloudflare'))
from import_d1 import load_snapshot


def validate_separation(state,preview,guest=False):
    names = ['IKIMONO_SESSION_SECRET']
    if not guest or 'IKIMONO_PREVIEW_PASSWORD' in state:
        names.append('IKIMONO_PREVIEW_PASSWORD')
    for name in names:
        value=state.get(name)
        previous=preview.get(name)
        if not isinstance(value,str) or not value.strip() or not isinstance(previous,str) or not previous.strip():
            raise ValueError('Candidate credentials are missing or reused')
        if hmac.compare_digest(value.strip().encode(),previous.strip().encode()):
            raise ValueError('Candidate credentials are missing or reused')


def main():
    global STAGE
    STAGE='credential-separation'
    state=json.loads(STATE.read_text())
    preview=json.loads((Path.home()/'.local/state/ikimono-cloudflare-preview/secrets.json').read_text())
    validate_separation(state,preview,guest=True)
    spec=importlib.util.spec_from_file_location('preview_checks',PREVIEW/'check.py')
    checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
    STAGE='deployment-contract'
    checks.check(ORIGIN,oauth_enabled=True,edge=True,state_path=STATE,expected_public_origin=ORIGIN,
                 guest=True,bundle_dir=HERE)
    STAGE='private-snapshot'
    rows=load_snapshot(Path('/var/tmp/ikimono-cloudflare-migration-private/firestore-20261010-production-candidate.sqlite3'),
        '049f0bad77707ed3e193f4eff3065a15f98c1a1347629137c712f3b1628b3a51')
    for token,owner,created_at,payload,photo,mime in rows['shares']:
        # Never log private token/URL/body; never mint an owner session or write.
        for suffix in ('','/photo'):
            STAGE='migrated-share-photo' if suffix else 'migrated-share-page'
            request=Request(ORIGIN+'/s/'+token+suffix,headers={
                'User-Agent':'ikimono-note-deployment-check/1.0'})
            with build_opener(checks.NoRedirect()).open(request,timeout=30) as response:
                if response.status!=200:raise ValueError('Migrated share unavailable')
                body=response.read()
                if suffix:
                    if body!=photo or response.headers['Content-Type']!=mime:
                        raise ValueError('Migrated photo mismatch')
                elif 'og:title' not in body.decode():raise ValueError('Migrated share page invalid')
    print('PASS: migrated share pages and exact photo bytes/MIME through actual Worker; no writes')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(f'FAIL: {STAGE} ({type(error).__name__}); private details withheld')
        raise SystemExit(2) from None
