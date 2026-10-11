"""Evaluation denominators and isolation without inference or network calls."""
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quality_benchmark as benchmark


class BenchmarkTests(unittest.TestCase):
    def fixture(self, directory):
        gold = {'version': 1, 'verified_at': '2026-10-11', 'themes': {'研究': {
            'target_recall': 1, 'milestones': [{'id': 'start', 'label': '研究開始',
                'years': [1900, 1900], 'keywords': ['研究開始']}], 'known_errors': []}}}
        for name in ('quality_gold.json', 'quality_holdout.json'):
            (directory / name).write_text(json.dumps(gold))
        (directory / 'before').mkdir()
        benchmark.write_json(directory / 'before' / 'manifest.json', {
            'gold_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                           for name in ('quality_gold.json', 'quality_holdout.json')}})
        return gold

    def test_generation_errors_are_failures_not_excluded_from_pass_rate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            event = {'year': 1900, 'title': '研究開始', 'description': '研究を始めた。',
                     'source': {'url': 'https://example.org'}}
            benchmark.write_json(directory / 'before' / 'core-1-0.json', {
                'theme': '研究', 'pipeline_version': 15, 'record': {'kind': 'result', 'theme': '研究', 'events': [event]}})
            benchmark.write_json(directory / 'before' / 'core-2-0.json', {'theme': '研究', 'record': {'kind': 'error', 'message': 'busy'}})
            report = benchmark.summarize(directory, 'before')
            core = report['groups']['core']
            self.assertEqual(core, {'planned': 3, 'finished': 2, 'passed': 1, 'failed_generations': 1, 'pass_rate': 0.5})
            self.assertEqual(report['groups']['holdout']['finished'], 0)

    def test_different_source_routes_cannot_be_compared(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            (directory / 'after').mkdir()
            for label, source in [('before', 'wikipedia'), ('after', 'searxng')]:
                manifest = dict.fromkeys(benchmark.CONDITIONS, '') | {'source': source}
                benchmark.write_json(directory / label / 'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'source'):
                benchmark.compare(directory, ['before', 'after'])
            self.assertFalse((directory / 'comparison.json').exists())

    def test_scoring_rejects_a_changed_evaluation_even_with_matching_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            frozen = json.loads((directory / 'before' / 'manifest.json').read_text())
            manifest = dict.fromkeys(benchmark.CONDITIONS, '') | frozen
            for label in ('before', 'after'):
                benchmark.write_json(directory / label / 'manifest.json', manifest)
            (directory / 'quality_gold.json').write_text('{"themes": {}}')
            with self.assertRaisesRegex(ValueError, 'Frozen evaluation changed'):
                benchmark.compare(directory, ['before', 'after'])
            self.assertFalse((directory / 'comparison.json').exists())

    def test_result_cannot_be_scored_as_a_different_theme(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            benchmark.write_json(directory / 'before' / 'core-1-0.json', {
                'theme': '別テーマ', 'record': {'kind': 'error'}})
            with self.assertRaisesRegex(ValueError, 'Result theme differs'):
                benchmark.summarize(directory, 'before')

    def test_modified_snapshot_is_rejected_before_running_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.fixture(directory)
            manifest = dict.fromkeys(benchmark.CONDITIONS, '') | {'sha256': {'timeline.py': 'old'}}
            (directory / 'before' / 'code').mkdir()
            (directory / 'before' / 'code' / 'timeline.py').write_text('changed')
            benchmark.write_json(directory / 'before' / 'manifest.json', manifest)
            with patch.object(benchmark.subprocess, 'run') as process:
                with self.assertRaisesRegex(ValueError, 'Snapshot code changed'):
                    benchmark.run(directory, 'before')
                process.assert_not_called()


if __name__ == '__main__':
    unittest.main()
