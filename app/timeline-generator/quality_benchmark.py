"""Isolated, resumable real-model comparison; never opens the application's DB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
MODULES = ('timeline.py', 'milestones.py', 'jobs.py', 'server.py', 'quality_eval.py', 'quality_benchmark.py')
CONDITIONS = ('source', 'source_filter', 'model', 'verify_model', 'search_url', 'ollama_url',
              'time_limit_seconds', 'core_rounds', 'holdout_rounds', 'gold_sha256')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


def validate_gold(directory, manifest):
    for name, digest in manifest['gold_sha256'].items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen evaluation changed: ' + name)


def snapshot(directory, label):
    target = directory / label
    if target.exists():
        raise ValueError('Snapshot already exists; use --run to resume it.')
    code = target / 'code'
    code.mkdir(parents=True, mode=0o700)
    hashes = {}
    for name in MODULES:
        shutil.copyfile(ROOT / name, code / name)
        hashes[name] = hashlib.sha256((code / name).read_bytes()).hexdigest()
    for name in ('quality_gold.json', 'quality_holdout.json'):
        frozen = directory / name
        if frozen.exists() and frozen.read_bytes() != (ROOT / name).read_bytes():
            raise ValueError('Evaluation set changed during the experiment.')
        if not frozen.exists():
            shutil.copyfile(ROOT / name, frozen)
    write_json(target / 'manifest.json', {
        'label': label, 'created_at': datetime.now(timezone.utc).isoformat(), 'sha256': hashes,
        'source': os.environ.get('TIMELINE_SOURCE', 'searxng'),
        'source_filter': os.environ.get('TIMELINE_SOURCE_FILTER', ''),
        'model': os.environ.get('TIMELINE_MODEL', 'gemma4:12b'),
        'verify_model': os.environ.get('TIMELINE_VERIFY_MODEL', 'qwen3.8:27b'),
        'search_url': os.environ.get('TIMELINE_SEARCH_URL', 'http://127.0.0.1:8081'),
        'ollama_url': os.environ.get('TIMELINE_OLLAMA_URL', 'http://127.0.0.1:11434'),
        'time_limit_seconds': 3600, 'core_rounds': 3, 'holdout_rounds': 1,
        'gold_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                        for name in ('quality_gold.json', 'quality_holdout.json')},
    })
    return target


def one(theme, output):
    import server
    import timeline
    final = None
    def emit(record):
        nonlocal final
        if record.get('kind') in ('result', 'error'):
            final = record
        if record.get('kind') != 'checkpoint':
            write_json(output.parent / 'status.json', {'theme': theme, 'output': output.name,
                       'updated_at': datetime.now(timezone.utc).isoformat(), **record})
    server.bounded_pipeline(timeline.parse_query(theme), emit)
    write_json(output, {'theme': theme, 'pipeline_version': timeline.PIPELINE_VERSION,
                       'record': final or {'kind': 'error', 'message': 'No final response'}})


def run(directory, label):
    target = directory / label
    manifest = json.loads((target / 'manifest.json').read_text())
    environment = dict(os.environ)
    for key, variable in [('source', 'TIMELINE_SOURCE'), ('source_filter', 'TIMELINE_SOURCE_FILTER'),
                          ('model', 'TIMELINE_MODEL'), ('verify_model', 'TIMELINE_VERIFY_MODEL'),
                          ('search_url', 'TIMELINE_SEARCH_URL'), ('ollama_url', 'TIMELINE_OLLAMA_URL')]:
        environment[variable] = manifest[key]
    for name, digest in manifest['sha256'].items():
        if hashlib.sha256((target / 'code' / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Snapshot code changed: ' + name)
    validate_gold(directory, manifest)
    for group, filename, rounds in [('holdout', 'quality_holdout.json', 1), ('core', 'quality_gold.json', 3)]:
        themes = json.loads((directory / filename).read_text())['themes']
        for number in range(1, rounds + 1):
            for index, theme in enumerate(themes):
                output = target / f'{group}-{number}-{index}.json'
                if output.exists():
                    continue
                print(f'{label} {group} round {number}: {theme}', flush=True)
                subprocess.run([sys.executable, str(target / 'code' / 'quality_benchmark.py'),
                                '--one', theme, '--output', str(output)],
                               cwd=target / 'code', env=environment, check=True, timeout=3630)
    print(label + ': all 21 real-model cases completed', flush=True)


def summarize(directory, label):
    from quality_eval import evaluate_result
    target = directory / label
    validate_gold(directory, json.loads((target / 'manifest.json').read_text()))
    rows = []
    for group, filename, rounds in [('holdout', 'quality_holdout.json', 1), ('core', 'quality_gold.json', 3)]:
        gold = json.loads((directory / filename).read_text())
        for number in range(1, rounds + 1):
            for index, theme in enumerate(gold['themes']):
                path = target / f'{group}-{number}-{index}.json'
                if not path.exists():
                    rows.append({'group': group, 'round': number, 'theme': theme, 'state': 'pending', 'passed': None})
                    continue
                saved = json.loads(path.read_text())
                if saved.get('theme') != theme:
                    raise ValueError('Result theme differs from frozen evaluation: ' + str(path))
                record = saved['record']
                if record.get('kind') != 'result':
                    rows.append({'group': group, 'round': number, 'theme': theme, 'state': 'failed',
                                 'passed': False, 'recall': 0, 'message': record.get('message')})
                    continue
                report = evaluate_result(gold, record, theme)
                passed = report.get('recall') == 1 and not report['known_errors'] and not report['duplicates']
                rows.append({'group': group, 'round': number, 'theme': theme, 'state': 'complete',
                             'passed': passed, 'pipeline_version': saved['pipeline_version'], **report})
    groups = {}
    for group in ('core', 'holdout'):
        cases = [row for row in rows if row['group'] == group]
        completed = [row for row in cases if row['state'] != 'pending']
        groups[group] = {'planned': len(cases), 'finished': len(completed),
                         'passed': sum(row['passed'] is True for row in completed),
                         'failed_generations': sum(row['state'] == 'failed' for row in cases),
                         'pass_rate': sum(row['passed'] is True for row in completed) / len(completed) if completed else None}
    return {'label': label, 'groups': groups, 'cases': rows}


def compare(directory, labels):
    manifests = [json.loads((directory / label / 'manifest.json').read_text()) for label in labels]
    differences = [key for key in CONDITIONS if manifests[0][key] != manifests[1][key]]
    if differences:
        raise ValueError('Conditions differ: ' + ', '.join(differences))
    for manifest in manifests:
        validate_gold(directory, manifest)
    reports = [summarize(directory, label) for label in labels]
    complete = all(group['planned'] == group['finished'] for report in reports for group in report['groups'].values())
    report = {'complete': complete, 'conditions_equal': True, 'snapshots': reports,
              'human_content_audit': 'required; automated matching does not establish factual accuracy',
              'limitations': ['Live retrieval and shared inference contention can vary between runs.',
                             'Held-out themes have one run per version; results are exploratory.']}
    write_json(directory / 'comparison.json', report)
    for result in reports:
        for group, totals in result['groups'].items():
            rate = '-' if totals['pass_rate'] is None else f"{totals['pass_rate']:.1%}"
            print(f"{result['label']} {group}: finished {totals['finished']}/{totals['planned']}; "
                  f"passed {totals['passed']}; rate {rate}; generation failures {totals['failed_generations']}")
    print('Full comparison complete' if complete else 'Incomplete; do not claim improvement yet')


def wait_for(directory, label):
    # Only wait for this experiment's files, never a service or production queue.
    deadline = time.monotonic() + 21 * 3630 + 900
    while time.monotonic() < deadline:
        report = summarize(directory, label)
        groups = report['groups']
        finished = sum(group['finished'] for group in groups.values())
        if finished == sum(group['planned'] for group in groups.values()):
            return
        print(f'Waiting for {label}: {finished}/21 cases finished', flush=True)
        time.sleep(45)
    raise TimeoutError('Previous experiment did not finish; do not overlap model runs.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'data' / 'quality-generalization-20261011')
    parser.add_argument('--snapshot')
    parser.add_argument('--run')
    parser.add_argument('--wait-for', help='Wait for this snapshot to finish before --run; avoids inference overlap')
    parser.add_argument('--one')
    parser.add_argument('--compare', nargs=2, metavar=('BEFORE', 'AFTER'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.one:
        one(args.one, args.output)
    elif args.snapshot:
        print(snapshot(directory, args.snapshot))
    elif args.run:
        if args.wait_for:
            wait_for(directory, args.wait_for)
        run(directory, args.run)
    elif args.compare:
        compare(directory, args.compare)
    else:
        parser.error('Specify --snapshot or --run')


if __name__ == '__main__':
    main()
