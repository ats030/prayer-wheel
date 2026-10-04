"""Failure-focused tests for date constraints, provenance, fetches, and HTTP boundaries."""
import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import server
import timeline as t


def setUpModule():
    # 既存の検証は一段階の処理を前提にする。二段階生成は MajorFirstTests で個別に有効にする。
    patcher = patch.object(t, 'MAJOR_FIRST', False)
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def mock_worker(query, connection):
    connection.send({"kind": "progress", "stage": "search", "message": "searching"})
    connection.send({"kind": "result", "events": []})
    connection.close()


def slow_worker(query, connection):
    time.sleep(10)


class QueryTests(unittest.TestCase):
    def test_full_period_and_normalized_keywords(self):
        q = t.parse_query("半導体　日本")
        self.assertEqual((q.topic, q.start, q.end, q.period), ("半導体 日本", None, None, "全期間"))

    def test_period_conditions_are_rejected_without_removing_them(self):
        for value in ["半導体 日本 １９８０年以降 2000年まで", "ローマ 紀元前500年〜100年", "ローマ 紀元前5世紀", "京都 20世紀", "京都 1900〜2000年", "京都 1900-2000", "京都 1980年代", "京都 昭和20年以降", "京都 (20世紀)", "1980年以降 京都", "京都 1900年", "京都 2000年まで"]:
            with self.subTest(value=value), self.assertRaisesRegex(t.TimelineError, "年代条件を外してください"):
                t.parse_query(value)
        for period in ['20世紀', '1980年代', '紀元前5世紀']:
            for suffix in ['以降', '以前', 'から', 'まで']:
                with self.subTest(period=period, suffix=suffix), self.assertRaises(t.TimelineError):
                    t.parse_query(f'京都 {period}{suffix}')
        for period in ['1980年代から2000年代まで', '19世紀〜20世紀', '昭和20年から平成元年まで', '紀元前500', '西暦1900']:
            with self.subTest(period=period), self.assertRaises(t.TimelineError):
                t.parse_query('京都 ' + period)

    def test_invalid_and_uninterpreted_filters(self):
        for value in [None, "", "2000年以降", "京都 2000〜1900年", "京都 0年以降", "京都 1980年代", "京都 昭和20年以降", "京都 令和5年まで", "a" * 181]:
            with self.subTest(value=value), self.assertRaises(t.TimelineError):
                t.parse_query(value)

    def test_historical_topic_name_is_not_a_date_filter(self):
        for value in ["1984", "１９８４", "20世紀フォックス", "20世紀少年", "2001年宇宙の旅", "百年戦争", "100年戦争", "GPT-4.1", "半導体 日本", "1968年の学生運動"]:
            with self.subTest(value=value):
                q = t.parse_query(value)
                self.assertEqual(q.topic, t.compact(value))
                self.assertEqual((q.start, q.end), (None, None))


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"url": "https://example.org/history", "title": "History", "text": "In 1971, the first coffee shop opened in Seattle. In 1987, the company was acquired."}]
        self.event = {"year": 1971, "date": "1971年", "title": "最初の店舗", "description": "シアトルに最初の店舗が開店した。", "source_id": 1, "quote": "In 1971, the first coffee shop opened in Seattle."}

    def test_reject_invented_quotes_dates_ids_and_out_of_range(self):
        self.assertEqual(len(t.validate_events([self.event], self.sources, t.parse_query("コーヒー"))), 1)
        for changes in [{"quote": "In 1971, the first coffee shop opened in Tokyo."}, {"year": 1987}, {"source_id": 2}, {"source_id": True}, {"year": 0}, {"year": -1971}]:
            with self.subTest(changes=changes):
                self.assertEqual(t.validate_events([self.event | changes], self.sources, t.parse_query("コーヒー")), [])
        self.assertEqual(t.validate_events([self.event], self.sources, t.Query("", "コーヒー", 1980)), [])

    def test_rejection_reasons_name_the_failed_check(self):
        cases = [({"quote": "In 1971, the first coffee shop opened in Tokyo."}, "引用が原文にない、または長さが範囲外"),
                 ({"year": 1987}, "年が引用・段落に書かれていない"),
                 ({"source_id": 2}, "年・出典番号の形式が不正")]
        for changes, reason in cases:
            with self.subTest(changes=changes):
                reasons = {}
                t.validate_events([self.event | changes], self.sources, t.parse_query("コーヒー"), reasons)
                self.assertEqual(reasons, {((self.event | changes)["year"], "最初の店舗"): reason})
        reasons = {}
        t.validate_events([self.event], self.sources, t.parse_query("コーヒー"), reasons)
        self.assertEqual(reasons, {})

    def test_display_year_cannot_disagree_with_sort_year(self):
        e = self.event | {"date": "2000年"}
        result = t.validate_events([e], self.sources, t.parse_query("コーヒー"))
        self.assertEqual(result[0]["date"], "1971年")

    def test_approximate_source_year_stays_approximate(self):
        e = self.event | {"year": 900, "date": "900年", "quote": "900年頃、文字によるコーヒーの記録がある。"}
        result = t.validate_events([e], [self.sources[0] | {"text": e["quote"]}], t.parse_query("コーヒー"))
        self.assertEqual(result[0]["date"], "900年ごろ")

    def test_altered_acronym_is_not_published(self):
        e = self.event | {"year": 1986, "date": "1986年", "title": "NSFNetの設立", "description": "学術研究用のNS1Netが作られた。", "quote": "1986年、学術研究用のNSFNetが作られた。"}
        self.assertEqual(t.validate_events([e], [self.sources[0] | {"text": e["quote"]}], t.parse_query("インターネット")), [])

    def test_century_is_not_falsely_precise(self):
        evidence = "Coffee was consumed in Yemen in the 15th century."
        e = self.event | {"year": 1401, "date": "15世紀", "quote": evidence}
        result = t.validate_events([e], [self.sources[0] | {"text": evidence}], t.parse_query("コーヒー"))
        self.assertEqual(result[0]["date"], "15世紀")
        self.assertFalse(t.date_supported(1450, "15世紀", evidence))

    def test_verifier_failure_never_publishes_unverified_events(self):
        output = {"theme": "コーヒー", "events": [self.event]}
        with patch.object(t, "search", return_value=[{}]), patch.object(t.WebReader, "fetch", return_value=self.sources[0]), patch.object(t, "model_json", side_effect=[output, t.TimelineError("verification failed")]):
            with self.assertRaises(t.TimelineError):
                t.build_timeline(t.parse_query("コーヒー"), lambda _: None)

    def test_semantic_rejection_is_removed_and_empty_is_honest(self):
        output = {"theme": "コーヒー", "events": [self.event]}
        with patch.object(t, "search", return_value=[{}]), patch.object(t.WebReader, "fetch", return_value=self.sources[0]), patch.object(t, "model_json", side_effect=[output, {"supported": []}]):
            result = t.build_timeline(t.parse_query("コーヒー"), lambda _: None)
        self.assertEqual(result["events"], [])
        self.assertIn("0件", result["notice"])


class FetchTests(unittest.TestCase):
    def test_mixed_dns_and_private_addresses_are_rejected(self):
        for ips in [["127.0.0.1"], ["169.254.169.254"], ["93.184.216.34", "10.0.0.1"], ["::1"]]:
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]
            with self.subTest(ips=ips), patch.object(socket, "getaddrinfo", return_value=records), self.assertRaises(t.TimelineError):
                t.public_url("https://example.org/")

    def test_redirect_to_private_host_does_not_fetch(self):
        reader = t.WebReader()
        def resolve(url):
            if "127.0.0.1" in url:
                raise t.TimelineError("private")
            return url, "example.org", "93.184.216.34"
        with patch.object(t, "public_url", side_effect=resolve), patch.object(reader, "allowed", return_value=True), patch.object(reader, "request", return_value=(302, {"location": "http://127.0.0.1/secret"}, b"", "https://example.org/")) as request:
            self.assertIsNone(reader.fetch({"url": "https://example.org/"}))
            self.assertEqual(request.call_count, 1)

    def test_robots_denial_does_not_fetch_article(self):
        reader = t.WebReader()
        with patch.object(t, "public_url", return_value=("https://example.org/", "example.org", "93.184.216.34")), patch.object(reader, "request", return_value=(200, {}, b"User-agent: *\nDisallow: /", "https://example.org/robots.txt")) as request:
            self.assertIsNone(reader.fetch({"url": "https://example.org/"}))
            self.assertEqual(request.call_count, 1)

    def test_article_excludes_navigation_and_scripts(self):
        p = t.ArticleParser()
        p.feed("<title>History</title><nav>In 1900 the navigation says an invented fact.</nav><script>1971 bad</script><p>In 1971, the first coffee shop opened in Seattle.</p>")
        self.assertIn("1971", p.text())
        self.assertNotIn("1900", p.text())
        self.assertNotIn("bad", p.text())

    def test_short_japanese_dated_paragraphs_are_retained(self):
        p = t.ArticleParser()
        p.feed("<p>1971年、シアトルに新店舗が開店。</p>")
        self.assertIn("1971年", p.text())


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = server.JobStore(cls.temp.name + "/test.sqlite3")
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.http.jobs = cls.store
        cls.http.worker = server.QueueWorker(cls.store, server.bounded_pipeline)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.store.close()
        cls.temp.cleanup()

    def request(self, payload, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.url + "/api/jobs", data=json.dumps(payload).encode(), headers=headers), timeout=5)

    def setUp(self):
        with self.store.connect() as db:
            db.execute("DELETE FROM jobs")
            db.execute("UPDATE counter SET value=0")

    def test_submit_returns_saved_state_without_waiting(self):
        with self.request({"query": "京都"}) as response:
            job = json.load(response)
            self.assertEqual(response.status, 201)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.request({"query": "京都"}) as response:
            self.assertEqual(json.load(response)["id"], job["id"])
            self.assertEqual(response.status, 200)
        with urlopen(self.url + f"/api/jobs/{job['id']}") as response:
            self.assertEqual(json.load(response)["state"], "queued")
        with urlopen(self.url + "/api/jobs") as response:
            self.assertEqual(json.load(response)["total"], 1)
        with urlopen(self.url + f"/timelines/{job['id']}") as response:
            self.assertIn(b'data-site="timeline-generator"', response.read())

    def test_rejected_period_inputs_create_no_jobs(self):
        for value in ["半導体 1980年以降", "京都 1900〜2000年", "ジャズ 20世紀", "京都 1980年代以降", "京都 紀元前500", "京都 西暦1900"]:
            with self.subTest(value=value), self.assertRaises(HTTPError) as raised:
                self.request({"query": value})
            self.assertEqual(raised.exception.code, 400)
            self.assertIn("年代条件を外してください", json.load(raised.exception)['error'])
        self.assertEqual(self.store.listing()['total'], 0)
        with self.request({'query': '20世紀フォックス'}) as response:
            self.assertFalse(json.load(response)['legacy_period'])

    def test_period_archive_is_readable_but_actions_return_conflict(self):
        job, _ = self.store.submit(t.parse_query('インターネット'))
        result = {'kind': 'result', 'events': [{'quote': 'original evidence'}], 'trace': {'batches_total': 1}}
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET cache_key=?, query=?, state='complete', result=? WHERE id=?", (json.dumps(['インターネット', 1980, None], ensure_ascii=False), 'インターネット 1980年以降', json.dumps(result), job['id']))
        with urlopen(self.url + f"/api/jobs/{job['id']}") as response:
            archived = json.load(response)
        self.assertNotIn('trace', archived['result'])
        self.assertTrue(archived['legacy_period'])
        self.assertEqual(archived['result'], {k: v for k, v in result.items() if k != 'trace'})
        for action in ['retry', 'regenerate']:
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(self.url + f"/api/jobs/{job['id']}/{action}", data=b'{}', headers={'Content-Type': 'application/json'}))
            self.assertEqual(raised.exception.code, 409)
            self.assertIn('閲覧専用', json.load(raised.exception)['error'])
        with self.request({'query': 'インターネット'}) as response:
            new = json.load(response)
            self.assertEqual(response.status, 201)
        self.assertNotEqual(new['id'], archived['id'])
        self.assertFalse(new['legacy_period'])
        quality = archived.pop('quality')
        self.assertEqual(quality['theme'], 'インターネット')
        stored = self.store.get(job['id'])
        self.assertEqual(stored['result'].pop('trace'), {'batches_total': 1})
        self.assertEqual(stored, archived)

    def test_delete_api_protection_origin_and_missing(self):
        job, _ = self.store.submit(t.parse_query('削除API'))
        path = self.url + f"/api/jobs/{job['id']}/delete"
        headers = {'Content-Type':'application/json'}
        with self.assertRaises(HTTPError) as raised:
            urlopen(Request(path, data=b'{}', headers=headers | {'Origin':'https://evil.example'}))
        self.assertEqual(raised.exception.code, 403)
        self.assertIsNotNone(self.store.get(job['id']))
        self.store.claim()
        self.store.record(job['id'], {'kind':'result','events':[{'year':1900}]})
        with self.assertRaises(HTTPError) as raised:
            urlopen(Request(path, data=b'{}', headers=headers))
        self.assertEqual(raised.exception.code, 409)
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET cache_key=? WHERE id=?', (json.dumps(['削除API',1980,None]),job['id']))
        with urlopen(Request(path, data=b'{}', headers=headers)) as response:
            self.assertTrue(json.load(response)['deleted'])
        with self.assertRaises(HTTPError) as raised:
            urlopen(Request(path, data=b'{}', headers=headers))
        self.assertEqual(raised.exception.code, 404)
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.url + f"/api/jobs/{job['id']}")
        self.assertEqual(raised.exception.code, 404)

    def test_absolute_deadline_terminates_worker(self):
        records = []
        started = time.monotonic()
        with patch.object(server, "pipeline_worker", slow_worker), patch.object(server, "REQUEST_TIME_LIMIT", 0.3):
            server.bounded_pipeline(t.parse_query("京都"), records.append)
        self.assertEqual(records[-1]["kind"], "error")
        self.assertLess(time.monotonic() - started, 3)

    def test_cross_origin_invalid_input_and_routes(self):
        for payload, origin, expected in [({"query": "京都"}, "https://evil.example", 403), ({"query": ""}, None, 400)]:
            with self.subTest(expected=expected), self.assertRaises(HTTPError) as raised:
                self.request(payload, origin)
            self.assertEqual(raised.exception.code, expected)
        for headers in [{"Host": "evil.example"}, {"Origin": "https://evil.example"}]:
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as raised:
                urlopen(Request(self.url + "/api/jobs", headers=headers))
            self.assertEqual(raised.exception.code, 403)
        for path, expected in [("/api/jobs/999999", 404), ("/timelines/999999", 404), ("/api/jobs?offset=-1", 400), ("/api/jobs?offset=99999999999999999999", 400), ("/data/timelines.sqlite3", 404)]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as raised:
                urlopen(self.url + path)
            self.assertEqual(raised.exception.code, expected)

    def test_action_boundaries(self):
        job, _ = self.store.submit(t.parse_query("再試行テスト"))
        identifier = job["id"]
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET state='failed', error='テスト失敗' WHERE id=?", (identifier,))
        path = self.url + f"/api/jobs/{identifier}/retry"
        for origin, expected in [("https://evil.example", 403), (None, 200)]:
            request = Request(path, data=b"{}", headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
            if expected == 403:
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request)
                self.assertEqual(raised.exception.code, expected)
            else:
                with urlopen(request) as response:
                    self.assertEqual(json.load(response)["state"], "queued")

    def test_worker_outlives_client_connection(self):
        temp = tempfile.TemporaryDirectory()
        store = server.JobStore(temp.name + "/jobs.sqlite3")
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def pipeline(query, emit, stopping):
            entered.set()
            release.wait(3)
            emit({"kind": "result", "events": []})
            finished.set()
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        http.jobs = store
        http.worker = server.QueueWorker(store, pipeline)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        http.worker.start()
        try:
            url = f"http://127.0.0.1:{http.server_port}"
            with urlopen(Request(url + "/api/jobs", data=b'{"query":"coffee"}', headers={"Content-Type": "application/json"}), timeout=3) as response:
                job = json.load(response)
            # The registration connection is closed before generation completes.
            self.assertTrue(entered.wait(3))
            self.assertEqual(store.get(job["id"])["state"], "running")
            release.set()
            self.assertTrue(finished.wait(3))
            with urlopen(url + f"/api/jobs/{job['id']}") as response:
                self.assertEqual(json.load(response)["state"], "complete")
        finally:
            release.set()
            http.worker.stop()
            http.shutdown()
            http.server_close()
            store.close()
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
