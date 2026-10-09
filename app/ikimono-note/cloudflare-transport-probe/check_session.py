"""Differential check against actual auth.py signing/reading, synthetic only."""
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auth

auth.SESSION_SECRET = 'synthetic-session-check'
now = time.time()
payload = {'sub': 'synthetic-account', 'email': '合成@example.invalid', 'exp': int(now) + 3600}
valid = auth.sign_session(payload)
body, signature = valid.split('.')
cases = [None, '', 'garbage', valid, auth.sign_session({**payload, 'exp': 1}),
         body + '.' + ('A' if signature[0] != 'A' else 'B') + signature[1:],
         auth.sign_session({**payload, 'sub': 'different'}).split('.')[0] + '.' + signature,
         body + '.' + signature + '.', valid + '=', body + '.' + signature[:-1] + 'B']
expected = [auth.read_session(c) for c in cases]
script = """
import assert from 'node:assert/strict';
import {readSession} from '../worker_session.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const {cases, expected, secret, now} = JSON.parse(input);
for (let i=0; i<cases.length; i++) assert.deepEqual(await readSession(cases[i], secret, now), expected[i]);
assert.equal(await readSession(cases[3], 'wrong-key', now), null);
assert.equal(await readSession('x'.repeat(4097), secret, now), null);
console.log('PASS: actual Python session signing/reading parity, UTF-8, forgery, expiry, malformed signatures, wrong key, bounds');
"""
subprocess.run(['/home/ats030/.nvm/versions/node/v24.19.0/bin/node', '--input-type=module', '-e', script],
               input=json.dumps({'cases': cases, 'expected': expected, 'secret': auth.SESSION_SECRET, 'now': now}),
               text=True, check=True, cwd=Path(__file__).resolve().parent)
