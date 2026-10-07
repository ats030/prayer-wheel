"""User priorities, storage migration and pipeline boundaries without live model calls."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

import milestones as m
import timeline as t
from jobs import JobStore, QueueWorker
import server

ITEM = {'name': '沖縄返還', 'year': 1972, 'note': '', 'url': ''}
EVENT = {'year': 1972, 'date': '1972年', 'title': '沖縄返還', 'description': '沖縄が返還された。'}


class MilestoneTests(unittest.TestCase):
    def test_slow_ordinary_search_leaves_a_targeted_search_window(self):
        query = t.parse_query('昭和'); query.requested_milestones = [ITEM]
        clock = [100.0]
        def slow_search(*args):
            clock[0] = 170.0
            return [{'url': 'https://example.org/history'}]
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'search', side_effect=slow_search), patch.object(t, 'requested_sources', return_value=[]) as requested, patch.object(t, 'SOURCE_FILTER', ''), patch.object(t.WebReader, 'fetch', return_value=None):
            t.build_timeline(query, lambda _: None)
        self.assertEqual(requested.call_args.args[1], 200.0)

    def test_overlapping_targeted_results_preserve_ordinary_fetch_order(self):
        ordinary = [{'url': f'normal{i}', 'title': f'original{i}'} for i in range(4)]
        targeted = [dict(ordinary[3], title='request'), dict(ordinary[2], title='request'), {'url': 'target', '_requested': True}]
        merged = t.merge_source_results(ordinary, targeted)
        self.assertEqual([r['url'] for r in merged], ['normal0', 'normal1', 'normal2', 'normal3', 'target'])
        self.assertEqual(merged[3]['title'], 'original3')
        self.assertTrue(merged[3]['_requested'])

    def test_requested_passage_survives_excerpt_budget(self):
        query = t.parse_query('昭和'); query.requested_milestones = [ITEM]
        passages = [{'text': f'{1900 + i}年に昭和の出来事が起きた。' + '背景の説明。' * 5,
                     'heading': '', 'date_heading': ''} for i in range(20)]
        requested = {'text': '1972年に沖縄返還が実現した。', 'heading': '', 'date_heading': ''}
        passages.insert(10, requested)
        self.assertIn(requested, t.select_passages(passages, query, budget=150))
        query = t.parse_query('昭和 沖縄'); query.requested_milestones = [ITEM]
        requested = {'text': '沖縄返還が実現した。', 'heading': '1972年', 'date_heading': '1972年'}
        self.assertEqual(t.select_passages([requested], query, budget=150), [requested])
        query.requested_milestones = [{'name': '第一項目'}, {'name': '第二項目'}]
        repeated = [{'heading': '', 'date_heading': '', 'text': f'19{i:02}年 第一項目 ' + '説明' * 100} for i in range(12)]
        second = {'heading': '', 'date_heading': '', 'text': '1972年 第二項目 ' + '説明' * 80}
        selected = t.select_passages(repeated + [second], query, budget=2400)
        self.assertIn(second, selected)

    def test_slow_targeted_fetches_do_not_starve_normal_fetches(self):
        blocked = threading.Event()
        ordinary_fetched = threading.Event()
        class Reader:
            def fetch(self, result):
                if result['url'].startswith('target'):
                    self.assertion = ordinary_fetched.wait(1)
                    blocked.wait(1)
                    return None
                ordinary_fetched.set(); blocked.set()
                return result
        reader = Reader()
        results = [{'url': f'target{i}'} for i in range(12)] + [{'url': 'normal'}]
        self.assertEqual(t.fetch_sources(reader, results, {'normal'}), [{'url': 'normal'}])
        self.assertTrue(reader.assertion)

    def test_invalid_requests_and_normalized_duplicates(self):
        for items in [None, [ITEM] * 13, [{'name': ''}], [{'name': '!!!'}], [ITEM, ITEM | {'name': '沖縄 返還'}], [ITEM | {'year': True}], [ITEM | {'year': 0}], [ITEM | {'year': '1972'}], [ITEM | {'url': 'javascript:alert(1)'}], [ITEM | {'url': 'https://u:p@example.org/'}], [ITEM | {'note': 'x\ny'}], [ITEM | {'name': 'x' * 121}], [ITEM | {'other': 1}]]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                m.normalize(items)
        self.assertEqual(m.normalize([{'name': ' 沖縄返還 '}]), [ITEM | {'year': None}])

    def test_status_distinguishes_not_yet_generated_and_rejected(self):
        self.assertEqual(m.report([ITEM], {'events': []})[0]['status'], 'pending')
        result = {'events': [EVENT], 'requested_milestones': [ITEM]}
        self.assertEqual(m.report([ITEM], result)[0]['status'], 'found')
        result['events'] = [EVENT | {'year': 1971}]
        self.assertEqual(m.report([ITEM], result)[0]['status'], 'mismatch')
        result['events'] = []
        result['stop_reason'] = 'time_limit'
        result['trace'] = {'rejected': [EVENT | {'reason': '引用が一致しない'}]}
        row = m.report([ITEM], result)[0]
        self.assertEqual(row['status'], 'missing')
        self.assertIn('引用が一致しない', row['reason'])
        self.assertIn('時間上限', row['reason'])

    def test_requested_sources_use_existing_search_provider_and_safe_reader(self):
        query = t.parse_query('昭和')
        query.requested_milestones = [ITEM | {'url': 'http://127.0.0.1/'}]
        with patch.object(t, 'web_search', return_value=[{'url': 'https://example.org/history', 'title': 'History'}]) as search:
            results = t.requested_sources(query, time.monotonic() + 10)
        self.assertEqual(search.call_args.args[0], '昭和 沖縄返還')
        self.assertTrue(all(r['_requested'] for r in results))
        reader = t.WebReader()
        with patch.object(t.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]):
            self.assertIsNone(reader.fetch(results[0]))
        with patch.object(t, 'SOURCE', 'wikipedia'), patch.object(t, 'web_search', return_value=[]):
            self.assertEqual(t.requested_sources(query, time.monotonic() + 10), [])

    def test_batch_priority_is_stable_and_evidence_still_required(self):
        ordinary = [{'passages': [{'text': '別の出来事', 'heading': ''}]}]
        priority = [{'passages': [{'text': '1972年に沖縄返還。', 'heading': ''}]}]
        self.assertEqual(t.prioritize_batches([ordinary, priority], [ITEM]), [priority, ordinary])
        query = t.parse_query('昭和'); query.requested_milestones = [ITEM]
        source = {'url': 'https://example.org/history', 'title': '昭和', 'text': '1972年に沖縄返還。'}
        proposal = EVENT | {'source_id': 1, 'quote': '1972年に沖縄返還。', 'check_query': 'Okinawa reversion'}
        with patch.object(t, 'model_json', return_value={'events': [proposal]}) as model:
            generated = t.generate_batch(query, [source], time.monotonic() + 60)
        self.assertIn('沖縄返還', model.call_args.args[1])
        self.assertIn('根拠ではなく', model.call_args.args[1])
        # A requested event still cannot pass with an invented quotation.
        self.assertEqual(t.validate_events([proposal | {'quote': '存在しない根拠の引用文です。'}], [source], query), [])
        result = t.timeline_result(query, [EVENT], [], time.monotonic())
        partial = t.partial_result(t.parse_query('昭和'), result, time.monotonic(), 'time_limit')
        self.assertEqual(partial['requested_milestones'], [ITEM])

    def test_verified_requested_event_survives_pruning(self):
        query = t.parse_query('昭和'); query.requested_milestones = [ITEM]
        other = EVENT | {'year': 1960, 'title': '別の出来事'}
        with patch.object(t, 'MAX_EVENTS', 1), patch.object(t, 'model_json', return_value={'ratings': [{'id': 0, 'tier': 'core'}, {'id': 1, 'tier': 'peripheral'}]}):
            self.assertEqual(t.prune_events(query, [other, EVENT], [EVENT], time.monotonic() + 60, []), [EVENT])
            query.requested_milestones = [ITEM | {'year': 1971}]
            self.assertEqual(t.prune_events(query, [other, EVENT], [EVENT], time.monotonic() + 60, []), [EVENT])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/jobs.sqlite3'
        self.store = JobStore(self.path)
        self.job = self.store.submit(t.parse_query('昭和'))[0]
        self.store.claim()
        self.original = {'kind': 'result', 'events': [EVENT]}
        self.store.record(self.job['id'], self.original)

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_save_preserves_result_and_state_and_checks_revision(self):
        saved = self.store.save_milestones(self.job['id'], [ITEM], 0)
        self.assertEqual(saved['result'], self.original)
        self.assertEqual(saved['state'], 'complete')
        self.assertEqual(saved['milestones_revision'], 1)
        with self.assertRaisesRegex(ValueError, '別の画面'):
            self.store.save_milestones(self.job['id'], [], 0)
        self.store.requeue(self.job['id'], 'regenerate')
        with self.assertRaisesRegex(ValueError, '待機・生成中'):
            self.store.save_milestones(self.job['id'], [], 1)
        self.assertEqual(self.store.get(self.job['id'])['requested_milestones'], [ITEM])
        self.store.close(); self.store = JobStore(self.path)
        self.assertEqual(self.store.get(self.job['id'])['requested_milestones'], [ITEM])

    def test_worker_receives_snapshot_on_regenerate(self):
        self.store.save_milestones(self.job['id'], [ITEM], 0)
        self.store.requeue(self.job['id'], 'regenerate')
        received = []
        def pipeline(query, emit, cancelled):
            received.extend(query.requested_milestones)
            emit(t.timeline_result(query, [], [], time.monotonic()))
            worker.stopping.set()
        worker = QueueWorker(self.store, pipeline)
        worker.run_queue()
        self.assertEqual(received, [ITEM])
        self.assertEqual(self.store.get(self.job['id'])['result']['requested_milestones'], [ITEM])

    def test_additive_migration_leaves_old_results_unchanged(self):
        self.store.close()
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE jobs DROP COLUMN requested_milestones')
            db.execute('ALTER TABLE jobs DROP COLUMN milestones_revision')
        self.store = JobStore(self.path)
        job = self.store.get(self.job['id'])
        self.assertEqual(job['requested_milestones'], [])
        self.assertEqual(job['milestones_revision'], 0)
        self.assertEqual(job['result'], self.original)

    def test_http_save_origin_conflict_and_report(self):
        http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        http.jobs = self.store; http.worker = QueueWorker(self.store, lambda *args: None)
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        root = f'http://127.0.0.1:{http.server_port}'
        url = root + f"/api/jobs/{self.job['id']}/milestones"
        payload = json.dumps({'items': [ITEM], 'revision': 0}).encode()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, data=payload, headers={'Content-Type': 'application/json', 'Origin': 'https://evil.example'}))
            self.assertEqual(error.exception.code, 403)
            with urlopen(Request(url, data=payload, headers={'Content-Type': 'application/json'})) as response:
                saved = json.load(response)
            self.assertEqual(saved['state'], 'complete')
            self.assertFalse(http.worker.wake.is_set())
            self.assertEqual(saved['milestone_report'][0]['status'], 'found')
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, data=payload, headers={'Content-Type': 'application/json'}))
            self.assertEqual(error.exception.code, 409)
            with urlopen(root + f"/api/jobs/{self.job['id']}") as response:
                self.assertTrue(json.load(response)['suggested_milestones'])
        finally:
            http.shutdown(); http.server_close(); thread.join()
