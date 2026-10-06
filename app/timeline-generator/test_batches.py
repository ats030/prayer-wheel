"""Batch coverage, verified checkpoints and hard-deadline integration tests."""
import json
import os
import re
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
    if schema is t.PRUNE_SCHEMA:
        # 擬似の関連度判定: 古い出来事（出力済み）を周辺的とし、そこから外させる。
        # 判定は一覧の並びによらず年で決める。分類は組をまたいで使い回すため（ats030-20t3o）。
        listing = json.loads(prompt.split('出来事:\n', 1)[1])
        return {'ratings': [{'id': e['id'], 'tier': 'peripheral' if e['year'] < 1910 - t.MAX_EVENTS else 'core'} for e in listing]}
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
    def run_generation(self, source, model=grounded_model, records=None, saturated=None):
        # 擬似モデルは1段落から1件を出すので、組の段落数を出力上限に揃えて組ごとの件数を固定する。
        # 毎組が上限で埋まるため、再生成は既定で止め、それを確かめるテストだけ有効にする。
        with patch.object(t, 'SATURATED_EVENTS', saturated or t.BATCH_EVENTS), patch.object(t, 'BATCH_PASSAGES', t.BATCH_EVENTS), patch.object(t, 'search', return_value=[{}]), patch.object(t.WebReader, 'fetch', return_value=source), patch.object(t, 'crosscheck_sources', return_value=[]), patch.object(t, 'model_json', side_effect=model):
            return t.build_timeline(t.parse_query('研究'), (records if records is not None else []).append)

    def test_over_the_cap_processing_continues_and_low_relevance_events_are_replaced(self):
        records, prompts = [], []
        def model(system, prompt, deadline, schema):
            prompts.append(prompt)
            return grounded_model(system, prompt, deadline, schema)
        result = self.run_generation(history_source(), model=model, records=records)
        self.assertEqual(len(result['events']), t.MAX_EVENTS)
        self.assertEqual(result['stop_reason'], 'sources_exhausted')
        self.assertEqual(result['trace']['batches_processed'], result['trace']['batches_total'])
        # 出力済みだった古い出来事が外れ、後の組の出来事が残る。
        self.assertEqual([e['year'] for e in result['events']], list(range(1910 - t.MAX_EVENTS, 1910)))
        self.assertEqual(result['events'], sorted(result['events'], key=lambda e: e['year']))
        self.assertTrue(all('_context' not in e for e in result['events']))
        checkpoints = [r for r in records if r['kind'] == 'checkpoint']
        self.assertEqual([len(r['events']) for r in checkpoints][:8], list(range(t.BATCH_EVENTS, t.MAX_EVENTS, t.BATCH_EVENTS)) + [t.MAX_EVENTS])
        self.assertIn(1800, [e['year'] for e in checkpoints[0]['events']])
        pruned = [r for r in result['trace']['rejected'] if r['stage'] == '関連度']
        self.assertEqual(sorted(r['year'] for r in pruned), list(range(1800, 1910 - t.MAX_EVENTS)))
        self.assertTrue(all('関連度が低い' in r['reason'] for r in pruned))
        # 評価で語を照合できるよう、外した候補の説明も記録する（ats030-1gqzq）
        self.assertTrue(all(r['description'] for r in pruned))
        # 外した出来事も採用済みとして渡し、再提案させない。
        self.assertIn('研究の出来事1800', prompts[-2])

    def test_invalid_relevance_answer_drops_the_newest_candidates(self):
        def model(system, prompt, deadline, schema):
            return {'ratings': [{'id': 999, 'tier': 'peripheral'}, 'x']} if schema is t.PRUNE_SCHEMA else grounded_model(system, prompt, deadline, schema)
        records = []
        result = self.run_generation(history_source(56 + 3), model=model, records=records)
        self.assertEqual(len(result['events']), t.MAX_EVENTS)
        # 判定を得られない組では今回加わった候補から外し、出力済みの出来事は残す。
        shown = [r for r in records if r['kind'] == 'checkpoint' and len(r['events']) < t.MAX_EVENTS][-1]['events']
        self.assertTrue(all(e in result['events'] for e in shown))
        pruned = [r for r in result['trace']['rejected'] if r['stage'] == '関連度']
        self.assertEqual(len(pruned), 56 + 3 - t.MAX_EVENTS)
        self.assertFalse({r['year'] for r in pruned} & {e['year'] for e in shown})
        self.assertTrue(all('判定を得られず' in r['reason'] for r in pruned))

    def test_relevance_tiers_remove_peripheral_before_newer_core_events(self):
        events = [saved_event(year) for year in range(1800, 1800 + t.MAX_EVENTS + 3)]
        fresh = events[-3:]
        tiers = {0: 'core', 1: 'peripheral', 2: 'context', len(events) - 1: 'core'}
        def model(system, prompt, deadline, schema):
            return {'ratings': [{'id': i, 'tier': tier} for i, tier in tiers.items()]}
        dropped = []
        with patch.object(t, 'model_json', side_effect=model):
            kept = t.prune_events(t.parse_query('研究'), events, fresh, time.monotonic() + 60, dropped)
        # 周辺的と判定した1件の次は、未判定（背景と同じ段）を今回の組の新しい方から外す。判定済みの中核は最後まで残す。
        self.assertEqual([d['year'] for d in dropped], [1801, 1800 + t.MAX_EVENTS + 1, 1800 + t.MAX_EVENTS])
        self.assertIn('周辺的', dropped[0]['reason'])
        self.assertTrue(all('判定を得られず' in d['reason'] for d in dropped[1:]))
        self.assertEqual(len(kept), t.MAX_EVENTS)
        self.assertIn(events[-1], kept)

    def test_relevance_tiers_are_reused_so_later_prunes_rate_only_new_events(self):
        events = [saved_event(year) for year in range(1800, 1800 + t.MAX_EVENTS + 1)]
        prompts = []
        def model(system, prompt, deadline, schema):
            listing = json.loads(prompt.split('出来事:\n', 1)[1])
            prompts.append([e['year'] for e in listing])
            return {'ratings': [{'id': e['id'], 'tier': 'peripheral' if e['year'] == 1801 else 'core'} for e in listing]}
        known = {}
        with patch.object(t, 'model_json', side_effect=model):
            kept = t.prune_events(t.parse_query('研究'), events, events[-1:], time.monotonic() + 60, [], known)
            newer = saved_event(1900)
            dropped = []
            t.prune_events(t.parse_query('研究'), kept + [newer], [newer], time.monotonic() + 60, dropped, known)
        # 上限到達後に毎組全件を分類し直すと約45秒かかるため、2回目は新しい1件だけを分類させる（ats030-20t3o）。
        self.assertEqual(len(prompts[0]), t.MAX_EVENTS + 1)
        self.assertEqual(prompts[1], [1900])
        self.assertEqual([d['year'] for d in dropped], [1900])

    def test_relevance_prompt_counts_domestic_firsts_as_core(self):
        events = [saved_event(year) for year in range(1800, 1800 + t.MAX_EVENTS + 1)]
        seen = []
        def model(system, prompt, deadline, schema):
            seen.append(system)
            return {'ratings': []}
        with patch.object(t, 'model_json', side_effect=model):
            t.prune_events(t.parse_query('コーヒー'), events, events[-1:], time.monotonic() + 60, [])
        # 「各地」だけでは日本初の喫茶店が周辺的と判定された（ats030-or5mw）。
        self.assertIn('各地（日本国内を含む）での最初の店', seen[0].split('context:')[0])

    def test_relevance_prompt_counts_era_defining_events_as_core(self):
        events = [saved_event(year) for year in range(1800, 1800 + t.MAX_EVENTS + 1)]
        seen = []
        def model(system, prompt, deadline, schema):
            seen.append(system)
            return {'ratings': []}
        with patch.object(t, 'model_json', side_effect=model):
            t.prune_events(t.parse_query('昭和'), events, events[-1:], time.monotonic() + 60, [])
        # 物の起源向けの基準だけでは、昭和の東京オリンピックや沖縄返還が背景的とされ外れた（ats030-20t3o）。
        self.assertIn('時代を代表する政治・外交・経済・社会の大事件', seen[0].split('context:')[0])

    def test_disjoint_material_retains_context_and_all_sources(self):
        sources = [history_source(35) | {'url': f'https://example.org/{i}'} for i in range(10)]
        for i, source in enumerate(sources):
            source['passages'] = [p | {'text': p['text'] + f'（資料{i}）'} for p in source['passages']]
        batches = list(t.material_batches(sources, t.parse_query('研究')))
        seen = []
        for batch in batches:
            self.assertLessEqual(sum(len(s['passages']) for s in batch), t.BATCH_PASSAGES)
            self.assertLessEqual(sum(len(p['text']) + len(p['heading']) for s in batch for p in s['passages']), t.MATERIAL_BUDGET)
            for source in batch:
                self.assertEqual(len(source['all_passages']), 35)
                seen.extend((source['url'], t.passage_key(p)) for p in source['passages'])
        self.assertEqual(len(seen), 350)
        self.assertEqual(len(set(seen)), 350)

    def test_short_passages_fill_a_batch_beyond_the_event_limit(self):
        batches = list(t.material_batches([history_source(60)], t.parse_query('研究')))
        self.assertEqual([len(b[0]['passages']) for b in batches], [t.BATCH_PASSAGES, t.BATCH_PASSAGES, 60 - 2 * t.BATCH_PASSAGES])
        self.assertGreater(t.BATCH_PASSAGES, t.BATCH_EVENTS)

    def test_passage_repeated_in_a_later_source_is_read_once(self):
        mirror = history_source(10) | {'url': 'https://example.net/mirror'}
        own = {'heading': '1950年', 'date_heading': '1950年', 'text': saved_event(1950)['quote']}
        mirror['passages'] = mirror['passages'] + [own]
        batches = list(t.material_batches([history_source(10), mirror], t.parse_query('研究')))
        read = [(s['url'], p['text']) for b in batches for s in b for p in s['passages']]
        self.assertEqual(len(read), 11)
        self.assertIn(('https://example.net/mirror', own['text']), read)
        # 照合用の全段落は出典ごとに残す。
        self.assertTrue(all(len(s['all_passages']) == len(next(x for x in [history_source(10), mirror] if x['url'] == s['url'])['passages']) for b in batches for s in b))

    def test_same_sentence_under_another_year_is_not_a_mirror(self):
        first = {'url': 'https://example.com/a', 'title': 'A', 'text': '', 'passages': [{'heading': '1950年', 'date_heading': '1950年', 'text': 'この年、研究所の新工場が稼働した。'}]}
        second = {'url': 'https://example.net/b', 'title': 'B', 'text': '', 'passages': [{'heading': '1972年', 'date_heading': '1972年', 'text': 'この年、研究所の新工場が稼働した。'}]}
        batches = list(t.material_batches([first, second], t.parse_query('研究')))
        read = [s['url'] for b in batches for s in b for p in s['passages']]
        self.assertEqual(sorted(read), ['https://example.com/a', 'https://example.net/b'])

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

    def test_model_timeout_is_the_remaining_deadline_not_a_fixed_cap(self):
        # Waiting in the shared proxy queue must not count against a short fixed timeout.
        response = {'message': {'content': '{"events": []}'}}
        with patch.object(t.time, 'monotonic', return_value=0), patch.object(t, 'json_request', return_value=response) as request:
            self.assertEqual(t.model_json('s', 'p', 900, t.EVENT_SCHEMA), {'events': []})
        self.assertEqual(request.call_args.kwargs['timeout'], 900)

    def test_busy_backend_is_retried_until_success(self):
        busy = t.HTTPError('http://x', 503, 'busy', {}, None)
        response = {'message': {'content': '{"events": []}'}}
        with patch.object(t, 'json_request', side_effect=[busy, busy, response]) as request, patch.object(t.time, 'sleep') as sleep:
            self.assertEqual(t.model_json('s', 'p', time.monotonic() + 600, t.EVENT_SCHEMA), {'events': []})
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_busy_verify_model_falls_back_to_the_event_model(self):
        busy = t.HTTPError('http://x', 503, 'busy', {}, None)
        response = {'message': {'content': '{"supported": []}'}}
        models = []
        def request(url, payload, timeout):
            models.append(payload['model'])
            if len(models) == 1:
                raise busy
            return response
        with patch.object(t, 'VERIFY_MODEL', 'qwen'), patch.object(t, 'MODEL', 'gemma'), \
                patch.object(t, 'json_request', side_effect=request), patch.object(t.time, 'sleep') as sleep:
            self.assertEqual(t.model_json('s', 'p', time.monotonic() + 600, t.VERIFY_SCHEMA), {'supported': []})
        self.assertEqual(models, ['qwen', 'gemma'])
        sleep.assert_not_called()

    def test_busy_backend_stops_at_the_deadline(self):
        clock = [0]
        def busy(*args, **kwargs):
            raise t.HTTPError('http://x', 503, 'busy', {}, None)
        def advance(seconds):
            clock[0] += seconds
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'json_request', side_effect=busy) as request, patch.object(t.time, 'sleep', side_effect=advance):
            with self.assertRaises(t.TimelineError) as caught:
                t.model_json('s', 'p', 60, t.EVENT_SCHEMA)
        self.assertIsInstance(caught.exception.__cause__, t.HTTPError)
        self.assertEqual(request.call_count, 6)  # t=0..50; no retry once a backoff would leave <5s

    def test_other_http_errors_are_not_retried(self):
        with patch.object(t, 'json_request', side_effect=t.HTTPError('http://x', 400, 'bad', {}, None)) as request:
            with self.assertRaises(t.TimelineError):
                t.model_json('s', 'p', time.monotonic() + 600, t.EVENT_SCHEMA)
        self.assertEqual(request.call_count, 1)

    def test_deadline_between_batches_preserves_verified_work(self):
        clock = [0]
        def finish_near_deadline(query, sources, emit, deadline, existing, generated, **_):
            clock[0] = t.TIME_LIMIT - 9
            return [saved_event(1900)], []
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'verify_batch', side_effect=finish_near_deadline):
            result = self.run_generation(history_source(35))
        self.assertEqual(result['stop_reason'], 'time_limit')
        self.assertEqual(len(result['events']), 1)
        self.assertIn('時間上限', result['notice'])

    def test_trace_records_batches_and_dropped_candidates(self):
        def model(system, prompt, deadline, schema):
            output = grounded_model(system, prompt, deadline, schema)
            if schema is t.VERIFY_SCHEMA:
                return {'supported': output['supported'][1:], 'rejected': [{'id': 0, 'reason': '年と出来事の対応が違う'}]}
            return {'events': output['events'] + [{'year': 1801, 'date': '1801年', 'title': '架空の出来事', 'description': '本文にない。', 'quote': '本文に存在しない引用文です。', 'source_id': 1}]}
        result = self.run_generation(history_source(10), model=model)
        trace = result['trace']
        self.assertEqual((trace['batches_total'], trace['batches_processed']), (2, 2))
        self.assertEqual(trace['sources'], ['https://example.org/history'])
        self.assertEqual(sum(len(b['passages']) for b in trace['batches']), 10)
        self.assertTrue(all(b['processed'] for b in trace['batches']))
        stages = {(r['stage'], r['batch']) for r in trace['rejected']}
        self.assertEqual(stages, {('検査', 1), ('検査', 2), ('検証', 1), ('検証', 2)})
        self.assertIn('年と出来事の対応が違う', {r['reason'] for r in trace['rejected']})
        self.assertEqual(len(result['events']), 8)
        # 採用記録は組ごとに分かれ、合わせると最終結果の出来事に一致する。
        self.assertTrue(all(isinstance(b['seconds'], float) and b['adopted'] for b in trace['batches']))
        # 組の遅延がどの段階で増えたかを分けるため、段階ごとの所要秒も残す（ats030-20t3o）。
        self.assertTrue(all({'generate', 'crosscheck', 'verify'} <= b['stages'].keys() for b in trace['batches']))
        self.assertEqual(sorted(tuple(a) for b in trace['batches'] for a in b['adopted']),
                         sorted((e['year'], e['title']) for e in result['events']))

    def test_source_filter_is_off_by_default(self):
        result = self.run_generation(history_source(7), model=grounded_model)
        self.assertNotIn('excluded_sources', result['trace'])

    def test_source_filter_drops_only_judged_unrelated_results_before_fetching(self):
        results = [{'title': '研究', 'url': 'https://example.org/a', 'content': ''},
                   {'title': '研究大学', 'url': 'https://example.org/b', 'content': ''},
                   {'title': '研究の歴史', 'url': 'https://example.org/c', 'content': ''}]
        fetched = []
        def model(system, prompt, deadline, schema):
            if schema is t.RELATED_SCHEMA:
                time.sleep(0.3)
                # 主題そのもの（id 0）と「テーマの歴史」（id 2）も無関係と答えるが、残す。
                return {'judgments': [{'id': i, 'subject': '', 'related': False} for i in range(3)]}
            return grounded_model(system, prompt, deadline, schema)
        started = time.monotonic()
        def fetch(reader, result):
            # 判定にかかった時間は本文取得の期限に足される。
            self.assertGreaterEqual(reader.deadline, started + 60.3)
            fetched.append(result['url'])
            return history_source(7)
        with patch.object(t, 'SOURCE_FILTER', 'model'), patch.object(t, 'BATCH_PASSAGES', t.BATCH_EVENTS), patch.object(t, 'search', return_value=results), \
                patch.object(t.WebReader, 'fetch', fetch), patch.object(t, 'crosscheck_sources', return_value=[]), patch.object(t, 'model_json', side_effect=model):
            result = t.build_timeline(t.parse_query('研究'), lambda _: None)
        self.assertEqual(sorted(fetched), ['https://example.org/a', 'https://example.org/c'])
        self.assertEqual(result['trace']['excluded_sources'], [{'title': '研究大学', 'url': 'https://example.org/b'}])

    def test_source_filter_keeps_a_museum_named_after_the_theme(self):
        query = t.parse_query('ラーメン')
        results = [{'title': 'ラーメン', 'url': 'u0'}, {'title': '新横浜ラーメン博物館', 'url': 'u1'}, {'title': 'ラーメン橋', 'url': 'u2'}]
        excluded = []
        with patch.object(t, 'model_json', return_value={'judgments': [{'id': i, 'subject': '', 'related': False} for i in (1, 2)]}):
            kept = t.related_sources(query, results, time.monotonic() + 60, excluded)
        self.assertEqual([r['url'] for r in kept], ['u0', 'u1'])
        self.assertEqual(excluded, [{'title': 'ラーメン橋', 'url': 'u2'}])

    def test_source_filter_keeps_everything_when_the_judgment_fails_or_removes_all(self):
        query = t.parse_query('研究')
        results = [{'title': '研究所', 'url': 'u1'}, {'title': '研究者', 'url': 'u2'}]
        all_out = {'judgments': [{'id': 0, 'subject': '', 'related': False}, {'id': 1, 'subject': '', 'related': False}]}
        for answer in (t.TimelineError('busy'), all_out, {'judgments': 'broken'}):
            excluded = []
            with patch.object(t, 'model_json', side_effect=[answer]):
                self.assertEqual(t.related_sources(query, results, time.monotonic() + 60, excluded), results)
            self.assertEqual(excluded, [])

    def test_next_batch_generates_while_current_batch_verifies(self):
        # 第2組の生成が第1組の照合中に始まり、照合は組の順で前の組の採用分を既出として受け取る（ats030-gk683）。
        second_generation, existing_seen = threading.Event(), []
        def model(system, prompt, deadline, schema):
            if schema is t.EVENT_SCHEMA and '"1801年"' in prompt:
                second_generation.set()
            if schema is t.VERIFY_SCHEMA:
                existing_seen.append(len(json.loads(prompt.split('既に採用済み:', 1)[1].split('\n候補:', 1)[0])))
                if len(existing_seen) == 1:
                    self.assertTrue(second_generation.wait(5))
            return grounded_model(system, prompt, deadline, schema)
        with patch.object(t, 'BATCH_EVENTS', 1):
            result = self.run_generation(history_source(3), model=model)
        self.assertEqual(existing_seen, [0, 1, 2])
        self.assertEqual([e['year'] for e in result['events']], [1800, 1801, 1802])

    def test_deadline_reached_before_unprefetched_batch_stops_cleanly(self):
        # 冒頭の時間検査と先行生成の検査の間に10秒を切っても、例外ではなく時間上限で止める。
        clock = [0]
        class Records(list):
            def append(self, record):
                if '第1組を整理' in record.get('message', ''):
                    clock[0] = t.TIME_LIMIT - 9.5
                super().append(record)
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(t.TimelineError) as caught:
                self.run_generation(history_source(3), records=Records())
        self.assertIn('時間上限', str(caught.exception))

    def test_trace_records_over_cap_proposals_separately(self):
        original = t.verify_batch
        def capped(*args, **kwargs):
            args[5]['limit'] = 2
            return original(*args, **kwargs)
        with patch.object(t, 'verify_batch', side_effect=capped):
            trace = self.run_generation(history_source(10))['trace']
        self.assertEqual({r['stage'] for r in trace['rejected']}, {'件数上限'})

    def test_saturated_batch_is_regenerated_with_wider_limit(self):
        systems = []
        def model(system, prompt, deadline, schema):
            if schema is t.EVENT_SCHEMA:
                systems.append(system)
                if '最大14件' in system:
                    # 再生成では1件目が同じ引用の言い換えで重複し、枠外だった別の引用の出来事が1件増える。
                    events = grounded_model(system, prompt, deadline, schema)['events']
                    paraphrase = events[0] | {'title': events[0]['title'] + 'が起こる'}
                    return {'events': [paraphrase] + events + [events[0] | {'year': 1799, 'title': '枠外の出来事', 'quote': '1799年、枠外の出来事。'}]}
            return grounded_model(system, prompt, deadline, schema)
        result = self.run_generation(history_source(t.BATCH_EVENTS + 3), model=model, saturated=14)
        self.assertEqual(['最大7件' in s for s in systems], [True, False, True])
        self.assertEqual(['最大14件' in s for s in systems], [False, True, False])
        # 枠外の出来事は検証まで届き、そこで資料と照合される。
        self.assertIn(1799, [r['year'] for r in result['trace']['rejected'] if r['batch'] == 1])
        self.assertEqual(result['trace']['batches'][0]['proposed'], t.BATCH_EVENTS + 1)
        self.assertNotIn('研究の出来事1800が起こる', [r['title'] for r in result['trace']['rejected']] + [e['title'] for e in result['events']])

    def test_saturated_retry_failure_keeps_first_proposals(self):
        def model(system, prompt, deadline, schema):
            if schema is t.EVENT_SCHEMA and '最大14件' in system:
                raise t.TimelineError('busy')
            return grounded_model(system, prompt, deadline, schema)
        result = self.run_generation(history_source(t.BATCH_EVENTS), model=model, saturated=14)
        self.assertEqual(len(result['events']), t.BATCH_EVENTS)

    def test_source_without_candidates_is_asked_again_alone(self):
        first = history_source(3)
        second = {'url': 'https://example.org/other', 'title': '別記事', 'passages': [{'heading': '背景', 'date_heading': '1850年', 'text': saved_event(1850)['quote']}]}
        second['text'] = second['passages'][0]['text']
        materials = []
        def model(system, prompt, deadline, schema):
            materials.append([m['source_id'] for m in json.loads(prompt.split('資料(JSON):\n', 1)[1])])
            events = grounded_model(system, prompt, deadline, schema)['events']
            # 初回は先頭の記事だけから選び、2本目の記事を読み飛ばす。
            return {'events': [e for e in events if e['source_id'] == 1] if len(materials) == 1 else events}
        with patch.object(t, 'model_json', side_effect=model):
            generated = t.generate_batch(t.parse_query('研究'), [first, second], time.monotonic() + 900)
        self.assertEqual(materials, [[1, 2], [2]])
        self.assertEqual(sorted(e['year'] for e in generated['valid']), [1800, 1801, 1802, 1850])
        self.assertEqual(generated['limit'], t.SATURATED_EVENTS)

    def test_unused_source_events_survive_a_full_widened_batch(self):
        first = history_source(14)
        second = {'url': 'https://example.org/other', 'title': '別記事', 'passages': [{'heading': '背景', 'date_heading': '1850年', 'text': saved_event(1850)['quote']}]}
        second['text'] = second['passages'][0]['text']
        def model(system, prompt, deadline, schema):
            events = grounded_model(system, prompt, deadline, schema)['events']
            if '最大14件' in system:
                return {'events': [e for e in events if e['source_id'] == 1][:14]}
            # 初回は先頭の記事から7件で枠を埋め、2本目の記事は後の問い合わせでだけ読む。
            return {'events': [e for e in events if e['source_id'] == 1][:7] if '"source_id": 1' in prompt else events}
        with patch.object(t, 'model_json', side_effect=model):
            generated = t.generate_batch(t.parse_query('研究'), [first, second], time.monotonic() + 900)
        self.assertIn(1850, [e['year'] for e in generated['valid']])
        self.assertEqual(generated['limit'], 15)

    def test_batch_using_every_source_is_not_asked_again(self):
        calls = []
        def model(system, prompt, deadline, schema):
            calls.append(prompt)
            return grounded_model(system, prompt, deadline, schema)
        with patch.object(t, 'model_json', side_effect=model):
            generated = t.generate_batch(t.parse_query('研究'), [history_source(3)], time.monotonic() + 900)
        self.assertEqual(len(calls), 1)
        self.assertEqual(generated['limit'], t.BATCH_EVENTS)

    def test_trace_marks_unprocessed_batches_after_deadline(self):
        clock = [0]
        def finish_near_deadline(query, sources, emit, deadline, existing, generated, dropped=None, **_):
            clock[0] = t.TIME_LIMIT - 9
            dropped.append({'year': 1800, 'date': '1800年', 'title': 'x', 'stage': '検証', 'reason': 'r'})
            return [saved_event(1900)], []
        with patch.object(t.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(t, 'verify_batch', side_effect=finish_near_deadline):
            trace = self.run_generation(history_source(35))['trace']
        self.assertEqual((trace['batches_processed'], trace['batches_total']), (1, 5))
        self.assertEqual([b['processed'] for b in trace['batches']], [True] + [False] * 4)
        self.assertEqual(trace['rejected'][0]['batch'], 1)

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
