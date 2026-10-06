#!/usr/bin/env python3
"""Exercise deployment Secret writes without calling Google Cloud."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [ROOT / 'app' / app / 'deploy-cloudrun.sh' for app in
           ('ikimono-note', 'omatsuri-map', 'shiseki-map')]
# onsen-map is an independent checkout, not part of this repository.
ONSEN = ROOT / 'app/onsen-map/deploy-cloudrun.sh'
if ONSEN.exists():
    SCRIPTS.append(ONSEN)

MOCK = '''#!/usr/bin/env python3
import json, os, sys
path = os.environ['MOCK_STATE']
with open(path) as f: state = json.load(f)
args = sys.argv[1:]
command = args[:3]
if args[:2] == ['secrets', 'describe']:
    sys.exit(0 if state['exists'] else 1)
elif args[:2] == ['secrets', 'create']:
    state['exists'] = True
elif command == ['secrets', 'versions', 'list']:
    if state.get('list_error'):
        print('metadata unavailable', file=sys.stderr)
        sys.exit(1)
    if state['versions']:
        print('projects/test/secrets/example/versions/' + str(len(state['versions'])))
elif command == ['secrets', 'versions', 'access']:
    if state.get('access_error'):
        print('access denied', file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(state['versions'][int(args[3]) - 1])
elif command == ['secrets', 'versions', 'add']:
    state['versions'].append(sys.stdin.read())
else:
    print('Unexpected command: ' + repr(args), file=sys.stderr)
    sys.exit(2)
with open(path, 'w') as f: json.dump(state, f)
'''


class SecretDeploymentTests(unittest.TestCase):
    def exercise(self, path, initial, values):
        source = path.read_text()
        match = re.search(r'^put_secret\(\) \{\n.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(match, path)
        # Guard against leaving the old, unconditional write in the deploy path.
        self.assertEqual(source.count('secrets versions add'), 1, path)
        self.assertIsNotNone(re.search(r'^put_secret ikimono-|^  put_secret .*jalan-a8mat',
                                       source, re.M), path)
        function = match.group()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            state = tmp / 'state.json'
            state.write_text(json.dumps(initial))
            mock = tmp / 'gcloud'
            mock.write_text(MOCK)
            mock.chmod(0o700)
            runner = tmp / 'runner.sh'
            runner.write_text('set -euo pipefail\n'
                              'say() { printf "%s\\n" "$*"; }\n'
                              'fail() { printf "%s\\n" "$*" >&2; exit 1; }\n'
                              + function + '\nput_secret example "$TEST_VALUE"\n')
            results = []
            for value in values:
                env = {**os.environ, 'GCLOUD': str(mock), 'PROJECT': 'test',
                       'MOCK_STATE': str(state), 'TEST_VALUE': value}
                result = subprocess.run(['bash', str(runner)], env=env,
                                        capture_output=True, text=True)
                if value:
                    self.assertNotIn(value, result.stdout + result.stderr, path)
                results.append(result)
            return json.loads(state.read_text()), results

    def test_unchanged_redeploys_do_not_add_versions(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                state, results = self.exercise(script, {'exists': True, 'versions': ['test-key']},
                                               ['test-key', 'test-key'])
                self.assertEqual(state['versions'], ['test-key'])
                self.assertTrue(all(r.returncode == 0 for r in results))

    def test_changed_value_adds_once(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                state, results = self.exercise(script, {'exists': True, 'versions': ['old-key']},
                                               ['new-key', 'new-key'])
                self.assertEqual(state['versions'], ['old-key', 'new-key'])
                self.assertTrue(all(r.returncode == 0 for r in results))

    def test_new_or_empty_secret_gets_one_version(self):
        for script in SCRIPTS:
            for exists in (True, False):
                with self.subTest(script=script, exists=exists):
                    state, results = self.exercise(script, {'exists': exists, 'versions': []},
                                                   ['new-key', 'new-key'])
                    self.assertTrue(state['exists'])
                    self.assertEqual(state['versions'], ['new-key'])
                    self.assertTrue(all(r.returncode == 0 for r in results))

    def test_trailing_newlines_are_significant(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                value = 'line-one\nline-two.\n\n'
                state, results = self.exercise(script, {'exists': True, 'versions': [value]},
                                               [value, value.rstrip('\n'), value.rstrip('\n')])
                self.assertEqual(state['versions'], [value, value.rstrip('\n')])
                self.assertTrue(all(r.returncode == 0 for r in results))

    def test_failed_reads_stop_before_writing(self):
        for script in SCRIPTS:
            for error in ('access_error', 'list_error'):
                with self.subTest(script=script, error=error):
                    state, results = self.exercise(script, {'exists': True, 'versions': ['old-key'],
                                                           error: True}, ['new-key'])
                    self.assertEqual(state['versions'], ['old-key'])
                    self.assertNotEqual(results[0].returncode, 0)

    def test_empty_input_is_not_written(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                state, results = self.exercise(script, {'exists': False, 'versions': []}, [''])
                self.assertFalse(state['exists'])
                self.assertEqual(state['versions'], [])
                self.assertEqual(results[0].returncode, 0)


if __name__ == '__main__':
    unittest.main()
