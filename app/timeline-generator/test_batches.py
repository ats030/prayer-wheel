"""Batch coverage, verified checkpoints and hard-deadline integration tests."""
import json
import os
import struct
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

import server
import timeline as t
from jobs import JobStore, QueueWorker


def checkpoint_worker(query, connection):
    connection.send({'kind': 'checkpoint', 'events': [saved_event(1900)], 'review_notes': []})
    connection.send({'kind': 'progress', 'stage': 'generate', 'message': 'next unverified batch'})
    time.sleep(10)


def empty_checkpoint_worker(query, connection):
    connection.send({'kind': 'checkpoint', 'events': []})
    time.sleep(10)


def error_after_checkpoint_worker(query, connection):
    connection.send({'kind': 'checkpoint', 'events': [saved_event(1900)]})
    connection.send({'kind': 'error', 'message': 'model failed'})
    connection.close()


def truncated_message_worker(query, connection):
    connection.send({'kind': 'checkpoint', 'events': [saved_event(1900)]})
    # Leave a valid frame header but only part of the declared payload on the pipe.
    os.write(connection.fileno(), struct.pack('!i', 10000) + b'partial')
    os._exit(1)


def saved_event(year):
    return {'year': year, 'date': f'{year}年', 'title': f'研究の出来事{year}',
            'description': '研究の取り組みが始まった。', 'quote': f'{year}年、研究の取り組みが始まった。',
            'source': {'url': 'https://example.org/history', 'title': '研究の歴史'}}


def history_source(count=110):
    passages = [{'heading': f'{year}年', 'date_heading': f'{year}年', 'text': saved_event(year)['quote']}
                for year in range(1800, 1800 + count)]
    return {'url': 'https://example.org/history', 'title': '研究の歴史',
            'text': ' '.join(p['text'] for p in passages), 'passages': passages}


def grounded_model(system, prompt, deadline, schema):
    if schema is t.VERIFY_SCHEMA:
        candidates = json.loads(prompt.split('候補:', 1)[1].split('\n比較資料:', 1)[0])
        return {'supported': list(range(len(candidates)))}
    sources = json.loads(prompt.split('資料(JSON):\n', 1)[1])
    events = []
    for source in sources:
        for passage in source['passages']:
            year = int(passage['date_heading'][:-1])
            event = saved_event(year)
            event.pop('source')
            events.append(event | {'source_id': source['source_id']})
    return {'events': events}


class BatchTests(unittest.TestCase):
    def run_generation(self, source, model=grounded_model, records=None):
        with patch.object(t, 'search', return_value=[{}]), patch.object(t.WebReader, 'fetch', return_value=source), patch.object(t, 'crosscheck_sources', return_value=[]), patch.object(t, 'model_json', side_effect=model):
            return t.build_timeline(t.parse_query('研究'), (records if records is not None else []).append)

    def test_more_than_thirty_candidates_survive_and_one_hundred_is_hard_cap(self):
        records = []
        result = self.run_generation(history_source(), records=records)
        self.assertEqual(len(result['events']), 100)
        self.assertEqual(result['stop_reason'], 'event_limit')
        self.assertEqual(len({e['year'] for e in result['events']}), 100)
        self.assertEqual(result['events'], sorted(result['events'], key=lambda e: e['year']))
        self.assertTrue(all('_context' not in e for e in result['events']))
        checkpoints = [r for r in records if r['kind'] == 'checkpoint']
        self.assertEqual([len(r['events']) for r in checkpoints], list(range(t.BATCH_EVENTS, 100, t.BATCH_EVENTS)) + [100])

    def test_disjoint_material_retains_context_and_all_sources(self):
        sources = [history_source(35) | {'url': f'https://example.org/{i}'} for i in range(10)]
        batches = list(t.material_batches(sources, t.parse_query('研究')))
        seen = []
        for batch in batches:
            self.assertLessEqual(sum(len(s['passages']) for s in batch), t.BATCH_EVENTS)
            self.assertLessEqual(sum(len(p['text']) + len(p['heading']) for s in batch for p in s['passages']), t.MATERIAL_BUDGET)
            for source in batch:
                self.assertEqual(len(source['all_passages']), 35)
                seen.extend((source['url'], t.passage_key(p)) for p in source['passages'])
        self.assertEqual(len(seen), 350)
        self.assertEqual(len(set(seen)), 350)

    def test_sparse_material_has_no_minimum_and_rejections_are_not_checkpoints(self):
        result = self.run_generation(history_source(2))
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(result['stop_reason'], 'sources_exhausted')
        records = []
        def reject(system, prompt, deadline, schema):
            return {'supported': []} if schema is t.VERIFY_SCHEMA else grounded_model(system, prompt, deadline, schema)
        result = self.run_generation(history_source(2), reject, records)
        self.assertEqual(result['events'], [])
        self.assertFalse(any(r['kind'] == 'checkpoint' for r in records))

    def run_with_failures(self, failing_calls, count=35):
        calls = 0
        def fail_some(system, prompt, deadline, schema):
            nonlocal calls
            calls += 1
            if calls in failing_calls:
                raise t.TimelineError('verification failed')
            return grounded_model(system, prompt, deadline, schema)
        records = []
        with patch('sys.stderr'):
            result = self.run_generation(history_source(count), fail_some, records)
        return result, records

    def test_one_failed_batch_is_skipped_and_later_batches_continue(self):
        # Calls 1-2 verify the first batch; call 4 is the second batch's verification.
        result, records = self.run_with_failures({4})
        self.assertEqual(result['stop_reason'], 'processing_error')
        checkpoints = [r['events'] for r in records if r['kind'] == 'checkpoint']
        sizes = [min(t.BATCH_EVENTS, 35 - start) for start in range(0, 35, t.BATCH_EVENTS)]
        del sizes[1]
        self.assertEqual([len(c) for c in checkpoints], [sum(sizes[:i + 1]) for i in range(len(sizes))])
        self.assertTrue(all(e in result['events'] for e in checkpoints[0]))

    def test_first_batch_failure_does_not_abort_generation(self):
        result, _ = self.run_with_failures({1})
        self.assertEqual(len(result['events']), 35 - t.BATCH_EVENTS)
        self.assertEqual(result['stop_reason'], 'processing_error')

    def test_repeated_failures_stop_and_keep_verified_batches(self):
        result, records = self.run_with_failures({3, 5}, count=50)
        self.assertEqual(result['stop_reason'], 'processing_error')
        self.assertEqual(len(result['events']), t.BATCH_EVENTS)
        self.assertEqual(result['events'], next(r['events'] for r in records if r['kind'] == 'checkpoint'))

    def test_failures_without_verified_events_raise(self):
        with self.assertRaises(t.TimelineError):
            self.run_with_failures({1, 3})

    def test_truncated_model_json_is_reported_with_cause(self):
        # The model hits num_predict and returns HTTP 200 with cut-off JSON.
        response = {'message': {'content': '{"events": [{"year": 1958, "title": "チキン'}, 'done_reason': 'length', 'eval_count': 3000}
        with patch.object(t, 'json_request', return_value=response):
            with self.assertRaises(t.TimelineError) as caught:
                t.model_json('s', 'p', time.monotonic() + 60, t.EVENT_SCHEMA)
        self.assertIn('done_reason=length', str(caught.exception.__cause__))
        self.assertNotIn('チキン', str(caught.exception.__cause__))

    def test_deadline_between_batches_preserves_verified_work(self):
        clock = [0]
        def finish_near_deadline(query, sources, emit, deadline, existing):
            clock[0] = t.TIME_LIMIT - 9
            return [saved_event(1900)], []
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'build_batch', side_effect=finish_near_deadline):
            result = self.run_generation(history_source(35))
        self.assertEqual(result['stop_reason'], 'time_limit')
        self.assertEqual(len(result['events']), 1)
        self.assertIn('時間上限', result['notice'])

    def test_deadline_before_any_verified_work_is_failure(self):
        clock = [0]
        def fetch(_):
            clock[0] = t.TIME_LIMIT - 9
            return history_source(35)
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'search', return_value=[{}]), patch.object(t.WebReader, 'fetch', side_effect=fetch):
            with self.assertRaises(t.TimelineError):
                t.build_timeline(t.parse_query('研究'), lambda _: None)

    def test_cross_batch_duplicate_evidence_and_title_variations_are_removed(self):
        first = saved_event(1900)
        self.assertEqual(t.merge_events([first], [first | {'title': '別の表現'}]), [first])
        self.assertEqual(t.merge_events([first], [first | {'title': '研究の出来事 1900', 'quote': '別の原文引用です。'}]), [first])
        self.assertEqual(len(t.merge_events([first], [saved_event(1901)])), 2)

    def test_distinct_events_in_one_quote_are_retained(self):
        first = saved_event(1900) | {'title': '鉄道開通', 'description': '鉄道が開通した。', 'quote': '1900年、鉄道が開通し、港が開港した。'}
        second = first | {'title': '港の開港', 'description': '港が開港した。'}
        self.assertEqual(t.merge_events([first], [second]), [first, second])


class CheckpointTests(unittest.TestCase):
    def test_service_stop_after_checkpoint_leaves_job_recoverable(self):
        records = []
        stopping = threading.Event()
        def emit(record):
            records.append(record)
            stopping.set()
        with patch.object(server, 'pipeline_worker', checkpoint_worker):
            server.bounded_pipeline(t.parse_query('研究'), emit, stopping)
        self.assertEqual([r['kind'] for r in records], ['progress'])

    def test_hard_deadline_stalled_child_keeps_checkpoint_and_terminates(self):
        records = []
        started = time.monotonic()
        with patch.object(server, 'pipeline_worker', checkpoint_worker), patch.object(server, 'REQUEST_TIME_LIMIT', 0.6):
            server.bounded_pipeline(t.parse_query('研究'), records.append)
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(records[-1]['kind'], 'result')
        self.assertEqual(records[-1]['stop_reason'], 'time_limit')
        self.assertEqual(records[-1]['events'], [saved_event(1900)])
        self.assertFalse(any(r['kind'] == 'checkpoint' for r in records))

    def test_empty_checkpoint_on_timeout_is_failure(self):
        records = []
        with patch.object(server, 'pipeline_worker', empty_checkpoint_worker), patch.object(server, 'REQUEST_TIME_LIMIT', 0.6):
            server.bounded_pipeline(t.parse_query('研究'), records.append)
        self.assertEqual(records[-1]['kind'], 'error')

    def test_explicit_worker_error_preserves_only_checkpoint(self):
        records = []
        with patch.object(server, 'pipeline_worker', error_after_checkpoint_worker):
            server.bounded_pipeline(t.parse_query('研究'), records.append)
        self.assertEqual(records[-1]['kind'], 'result')
        self.assertEqual(records[-1]['stop_reason'], 'processing_error')

    def test_child_dying_mid_message_keeps_verified_checkpoint(self):
        records = []
        with patch.object(server, 'pipeline_worker', truncated_message_worker):
            server.bounded_pipeline(t.parse_query('研究'), records.append)
        self.assertEqual(records[-1]['kind'], 'result')
        self.assertEqual(records[-1]['stop_reason'], 'processing_error')
        self.assertEqual(records[-1]['events'], [saved_event(1900)])

    def test_database_emit_failure_is_not_masked_by_checkpoint(self):
        def emit(record):
            raise OSError('database disk full')
        with patch.object(server, 'pipeline_worker', error_after_checkpoint_worker):
            with self.assertRaisesRegex(OSError, 'database disk full'):
                server.bounded_pipeline(t.parse_query('研究'), emit)

    def test_partial_result_is_cached_and_fifo_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory + '/jobs.sqlite3')
            first, _ = store.submit(t.parse_query('研究'))
            second, _ = store.submit(t.parse_query('次のテーマ'))
            def pipeline(query, emit, stopping):
                server.bounded_pipeline(query, emit, stopping)
            worker = QueueWorker(store, pipeline)
            with patch.object(server, 'pipeline_worker', checkpoint_worker), patch.object(server, 'REQUEST_TIME_LIMIT', 0.6):
                worker.start()
                try:
                    deadline = time.monotonic() + 5
                    while store.get(second['id'])['state'] != 'complete' and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertEqual(store.get(second['id'])['state'], 'complete')
                    saved = store.get(first['id'])
                    self.assertEqual(saved['state'], 'complete')
                    self.assertIn('時間上限', saved['message'])
                    reused, created = store.submit(t.parse_query('研究'))
                    self.assertFalse(created)
                    self.assertEqual(reused['result'], saved['result'])
                finally:
                    worker.stop()
                    store.close()


if __name__ == '__main__':
    unittest.main()
