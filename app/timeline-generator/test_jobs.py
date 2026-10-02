"""Persistence, concurrency and failure-focused queue tests (no model calls)."""
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import time
import unittest
import json

from jobs import JobStore, QueueWorker, JobCancellation
from timeline import Query, TimelineError, parse_query
from server import bounded_pipeline
from unittest.mock import patch
import server


def cancellable_worker(query, connection):
    connection.send({'kind':'progress', 'message':'started'})
    time.sleep(10)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + "/jobs.sqlite3"
        self.store = JobStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def submit(self, value):
        return self.store.submit(parse_query(value))[0]

    def test_delete_rules_and_identifier_reuse(self):
        for legacy in [False, True]:
            for state in ['queued', 'running', 'complete', 'failed']:
                for events in [None, [], [{'year': 1984}]]:
                    with self.subTest(legacy=legacy, state=state, events=events):
                        job = self.submit(f'テーマ {legacy} {state} {len(str(events))}')
                        result = None if events is None else json.dumps({'events': events})
                        key = json.dumps([job['topic'], 1980 if legacy else None, None])
                        with self.store.connect() as db:
                            db.execute('UPDATE jobs SET state=?,cache_key=?,result=? WHERE id=?', (state, key, result, job['id']))
                        allowed = legacy or state in ['queued', 'running'] or not events
                        self.assertEqual(self.store.get(job['id'])['can_delete'], allowed)
                        listed = next(j for j in self.store.listing()['jobs'] if j['id']==job['id'])
                        self.assertEqual(listed['can_delete'], allowed)
                        if allowed:
                            self.assertTrue(self.store.delete(job['id'])['deleted'])
                            self.assertIsNone(self.store.get(job['id']))
                        else:
                            before = self.store.get(job['id'])
                            with self.assertRaisesRegex(ValueError, '収録済み'):
                                self.store.delete(job['id'])
                            self.assertEqual(self.store.get(job['id']), before)
        job = self.submit('削除して再登録')
        self.store.delete(job['id'])
        replacement = self.submit('削除して再登録')
        self.assertGreater(replacement['id'], job['id'])
        self.store.record(job['id'], {'kind':'result','events':[{'year':1900}]})
        self.assertIsNone(self.store.get(job['id']))
        self.assertEqual(self.store.get(replacement['id'])['state'], 'queued')
        self.assertIsNone(self.store.delete(9999999))

    def test_delete_terminates_running_subprocess(self):
        job = self.submit('子プロセス取消')
        self.store.claim()
        entered = threading.Event()
        records = []
        def emit(record):
            records.append(record)
            entered.set()
            self.store.record(job['id'], record)
        token = JobCancellation(self.store, job['id'], threading.Event())
        with patch.object(server, 'pipeline_worker', cancellable_worker):
            thread = threading.Thread(target=bounded_pipeline, args=(parse_query('子プロセス取消'), emit, token))
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.store.delete(job['id'])
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertEqual([r['kind'] for r in records], ['progress'])
            finally:
                self.store.delete(job['id'])
                thread.join(3)

    def test_completion_wins_delete_race_and_protects_result(self):
        job = self.submit('完了直前')
        self.store.claim()
        self.assertTrue(self.store.get(job['id'])['can_delete'])
        self.store.record(job['id'], {'kind':'result','events':[{'year':1900}]})
        with self.assertRaisesRegex(ValueError, '収録済み'):
            self.store.delete(job['id'])

    def test_delete_running_cancels_and_continues_without_resurrection(self):
        first = self.submit('取り消す')
        second = self.submit('次のテーマ')
        entered, cancelled, done = threading.Event(), threading.Event(), threading.Event()
        def pipeline(query, emit, stopping):
            if query.topic == '取り消す':
                entered.set()
                if stopping.wait(3):
                    cancelled.set()
                emit({'kind':'result','events':[{'year':1900}]})
            else:
                emit({'kind':'result','events':[]})
                done.set()
        worker = QueueWorker(self.store, pipeline)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.store.delete(first['id'])
            self.assertTrue(cancelled.wait(3))
            self.assertTrue(done.wait(3))
            self.assertIsNone(self.store.get(first['id']))
            self.assertEqual(self.store.get(second['id'])['state'], 'complete')
            self.assertTrue(worker.thread.is_alive())
        finally:
            worker.stop()

    def test_simultaneous_normalized_submissions_share_one_job(self):
        values = ["半導体 日本", "半導体　日本", " 半導体  日本 "] * 8
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(self.submit, values))
        self.assertEqual(len({job["id"] for job in jobs}), 1)
        self.assertEqual(self.store.listing()["total"], 1)
        self.assertNotEqual(self.submit("日本 半導体")["id"], jobs[0]["id"])
        self.assertNotEqual(self.submit("半導体 米国")["id"], jobs[0]["id"])

    def test_submit_rejects_bounded_query_objects(self):
        with self.assertRaises(TimelineError):
            self.store.submit(Query('京都', '京都', 1980))
        with self.assertRaises(TimelineError):
            self.store.submit(Query('京都 20世紀', '京都'))
        self.assertEqual(self.store.listing()['total'], 0)

    def test_period_archive_is_separate_and_read_only_in_every_state(self):
        legacy = self.submit('インターネット')
        self.store.claim()
        result = {'kind': 'result', 'events': [{'quote': 'stored original'}]}
        self.store.record(legacy['id'], result)
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET cache_key=?,query=? WHERE id=?', (json.dumps(['インターネット', 1980, None], ensure_ascii=False), 'インターネット 1980年以降', legacy['id']))
        full = self.submit('インターネット')
        self.assertNotEqual(full['id'], legacy['id'])
        self.assertFalse(full['legacy_period'])
        self.assertEqual(self.submit('インターネット')['id'], full['id'])
        for state in ['complete', 'failed', 'queued', 'running']:
            with self.store.connect() as db:
                db.execute('UPDATE jobs SET state=? WHERE id=?', (state, legacy['id']))
            before = self.store.get(legacy['id'])
            self.assertTrue(before['legacy_period'])
            self.assertEqual(before['topic'], 'インターネット')
            self.assertIn('1980年', before['period'])
            self.assertEqual(before['result'], result)
            for action in ['retry', 'regenerate']:
                with self.subTest(state=state, action=action), self.assertRaisesRegex(ValueError, '閲覧専用'):
                    self.store.requeue(legacy['id'], action)
            self.assertEqual(self.store.get(legacy['id']), before)
        archived_row = next(row for row in self.store.listing()['jobs'] if row['id'] == legacy['id'])
        self.assertTrue(archived_row['legacy_period'])
        self.assertNotIn('cache_key', archived_row)
        self.assertNotIn('stored original', str(archived_row))

    def test_worker_skips_old_period_request_and_continues(self):
        legacy = self.submit('インターネット')
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET cache_key=?,query=? WHERE id=?', (json.dumps(['インターネット', 1980, None], ensure_ascii=False), 'インターネット 1980年以降', legacy['id']))
        full = self.submit('インターネット')
        done, seen = threading.Event(), []
        def pipeline(query, emit, stopping):
            seen.append((query.topic, query.start, query.end))
            emit({'kind': 'result', 'events': []})
            done.set()
        worker = QueueWorker(self.store, pipeline)
        worker.start()
        try:
            self.assertTrue(done.wait(3))
            self.assertEqual(seen, [('インターネット', None, None)])
            self.assertEqual(self.store.get(full['id'])['state'], 'complete')
            self.assertIn('閲覧専用', self.store.get(legacy['id'])['error'])
        finally:
            worker.stop()

    def test_fifo_recovery_preserves_results_and_interrupted_order(self):
        first, second = self.submit("京都"), self.submit("コーヒー")
        self.assertEqual(self.store.claim()["id"], first["id"])
        self.store.close()
        self.store = JobStore(self.path)
        self.assertEqual(self.store.claim()["id"], first["id"])
        result = {"kind": "result", "events": [], "notice": "確認できた出来事は0件です。"}
        self.store.record(first["id"], result)
        self.assertEqual(self.store.claim()["id"], second["id"])
        self.assertEqual(self.submit("京都")["result"], result)
        self.store.close()
        self.store = JobStore(self.path)
        self.assertEqual(self.submit("京都")["result"], result)
        self.assertEqual(self.store.claim()["id"], second["id"])

    def test_retry_moves_to_tail_and_failed_refresh_keeps_old_result(self):
        first = self.submit("京都")
        self.store.claim()
        result = {"kind": "result", "events": [{"quote": "原文", "source": {"url": "https://example.org/"}}]}
        self.store.record(first["id"], result)
        second = self.submit("コーヒー")
        self.store.requeue(first["id"], "regenerate")
        self.assertEqual(self.store.claim()["id"], second["id"])
        self.store.record(second["id"], {"kind": "error", "message": "失敗"})
        self.assertEqual(self.store.claim()["id"], first["id"])
        self.store.record(first["id"], {"kind": "error", "message": "更新失敗"})
        self.assertEqual(self.store.get(first["id"])["result"], result)
        third = self.submit("ジャズ")
        self.store.requeue(first["id"], "retry")
        self.assertEqual(self.store.claim()["id"], third["id"])
        self.assertEqual(self.store.get(first["id"])["state"], "queued")

    def test_simultaneous_retries_enqueue_once(self):
        job = self.submit("京都")
        self.store.claim()
        self.store.record(job["id"], {"kind": "error", "message": "失敗"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(lambda _: self.store.requeue(job["id"], "retry"), range(24)))
        self.assertEqual(len({row["queue_order"] for row in rows}), 1)
        self.assertEqual(self.store.claim()["id"], job["id"])
        self.assertIsNone(self.store.claim())

    def test_single_owner_and_paged_listing(self):
        with self.assertRaises(BlockingIOError):
            JobStore(self.path)
        for i in range(55):
            self.submit(f"テーマ{i}")
        page = self.store.listing(offset=50)
        self.assertEqual((page["total"], len(page["jobs"])), (55, 5))
        self.assertNotIn("result", page["jobs"][0])

    def test_listing_counts_preserve_empty_unbuilt_and_previous_results(self):
        job = self.submit("研究")
        row = self.store.listing()["jobs"][0]
        self.assertIsNone(row["event_count"])
        self.assertIs(row["has_result"], False)
        self.store.claim()
        self.store.record(job["id"], {"kind": "result", "events": [], "stop_reason": "sources_exhausted"})
        self.assertEqual(self.store.listing()["jobs"][0]["event_count"], 0)
        self.store.requeue(job["id"], "regenerate")
        self.store.claim()
        result = {"kind": "result", "events": [{"quote": "private quote"}, {"quote": "second quote"}], "stop_reason": "time_limit"}
        self.store.record(job["id"], result)
        row = self.store.listing()["jobs"][0]
        self.assertEqual((row["event_count"], row["stop_reason"]), (2, "time_limit"))
        self.assertIs(row["has_result"], True)
        self.assertNotIn("private quote", str(row))
        self.assertNotIn("result", row)
        self.store.requeue(job["id"], "regenerate")
        row = self.store.listing()["jobs"][0]
        self.assertEqual((row["state"], row["event_count"]), ("queued", 2))
        self.assertEqual(self.store.get(job["id"])["result"], result)

    def test_worker_continues_after_exception_and_reuses_complete_result(self):
        first, second = self.submit("失敗するテーマ"), self.submit("成功するテーマ")
        seen = []
        done = threading.Event()
        def pipeline(query, emit, stopping):
            seen.append(query.topic)
            if query.topic == "失敗するテーマ":
                raise RuntimeError("upstream")
            emit({"kind": "result", "events": [], "notice": "0件"})
            done.set()
        worker = QueueWorker(self.store, pipeline)
        worker.start()
        try:
            self.assertTrue(done.wait(3))
            self.assertEqual(self.store.get(first["id"])["state"], "failed")
            self.assertEqual(self.store.get(second["id"])["state"], "complete")
            self.submit("成功するテーマ")
            self.assertEqual(seen, ["失敗するテーマ", "成功するテーマ"])
        finally:
            worker.stop()

    def test_stopping_active_pipeline_leaves_recoverable_job(self):
        job = self.submit("京都")
        entered = threading.Event()
        def pipeline(query, emit, stopping):
            entered.set()
            stopping.wait(3)
        worker = QueueWorker(self.store, pipeline)
        worker.start()
        self.assertTrue(entered.wait(3))
        worker.stop()
        self.assertEqual(self.store.get(job["id"])["state"], "running")
        self.store.close()
        self.store = JobStore(self.path)
        self.assertEqual(self.store.get(job["id"])["state"], "queued")

    def test_cancel_deadline_worker_promptly_without_failure(self):
        from test_timeline import slow_worker
        stopping = threading.Event()
        stopping.set()
        records = []
        start = time.monotonic()
        with patch.object(server, "pipeline_worker", slow_worker):
            bounded_pipeline(parse_query("京都"), records.append, stopping)
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
