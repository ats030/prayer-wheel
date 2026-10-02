"""Failure-focused tests for date constraints, provenance, fetches, and HTTP boundaries."""
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import server
import timeline as t


def mock_worker(query, connection):
    connection.send({"kind": "progress", "stage": "search", "message": "searching"})
    connection.send({"kind": "result", "events": []})
    connection.close()


def slow_worker(query, connection):
    time.sleep(10)


class QueryTests(unittest.TestCase):
    def test_compound_filters_and_full_width(self):
        q = t.parse_query("半導体 日本 １９８０年以降 2000年まで")
        self.assertEqual((q.topic, q.start, q.end), ("半導体 日本", 1980, 2000))

    def test_bce_and_century_boundaries(self):
        q = t.parse_query("ローマ 紀元前500年〜100年")
        self.assertEqual((q.start, q.end), (-500, 100))
        q = t.parse_query("ローマ 紀元前5世紀")
        self.assertEqual((q.start, q.end), (-500, -401))
        q = t.parse_query("京都 20世紀")
        self.assertEqual((q.start, q.end), (1901, 2000))

    def test_invalid_and_uninterpreted_filters(self):
        for value in [None, "", "2000年以降", "京都 2000〜1900年", "京都 0年以降", "京都 1980年代", "京都 昭和20年以降", "京都 令和5年まで", "a" * 181]:
            with self.subTest(value=value), self.assertRaises(t.TimelineError):
                t.parse_query(value)

    def test_historical_topic_name_is_not_a_date_filter(self):
        self.assertEqual(t.parse_query("100年戦争").topic, "100年戦争")


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sources = [{"url": "https://example.org/history", "title": "History", "text": "In 1971, the first coffee shop opened in Seattle. In 1987, the company was acquired."}]
        self.event = {"year": 1971, "date": "1971年", "title": "最初の店舗", "description": "シアトルに最初の店舗が開店した。", "source_id": 1, "quote": "In 1971, the first coffee shop opened in Seattle."}

    def test_reject_invented_quotes_dates_ids_and_out_of_range(self):
        self.assertEqual(len(t.validate_events([self.event], self.sources, t.parse_query("コーヒー"))), 1)
        for changes in [{"quote": "In 1971, the first coffee shop opened in Tokyo."}, {"year": 1987}, {"source_id": 2}, {"source_id": True}, {"year": 0}, {"year": -1971}]:
            with self.subTest(changes=changes):
                self.assertEqual(t.validate_events([self.event | changes], self.sources, t.parse_query("コーヒー")), [])
        self.assertEqual(t.validate_events([self.event], self.sources, t.parse_query("コーヒー 1980年以降")), [])

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
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    def request(self, payload, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.url + "/api/timeline", data=json.dumps(payload).encode(), headers=headers), timeout=5)

    def test_stream_and_no_saved_state(self):
        with patch.object(server, "pipeline_worker", mock_worker):
            with self.request({"query": "京都"}) as response:
                records = [json.loads(line) for line in response]
                self.assertEqual([r["kind"] for r in records], ["progress", "result"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_absolute_deadline_terminates_worker_and_releases_slot(self):
        started = time.monotonic()
        with patch.object(server, "pipeline_worker", slow_worker), patch.object(server, "REQUEST_TIME_LIMIT", 0.3):
            with self.request({"query": "京都"}) as response:
                records = [json.loads(line) for line in response]
        self.assertEqual(records[-1]["kind"], "error")
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(server.SLOT.acquire(timeout=2))
        server.SLOT.release()

    def test_cross_origin_invalid_input_and_busy(self):
        for payload, origin, expected in [({"query": "京都"}, "https://evil.example", 403), ({"query": ""}, None, 400)]:
            with self.subTest(expected=expected), self.assertRaises(HTTPError) as raised:
                self.request(payload, origin)
            self.assertEqual(raised.exception.code, expected)
        server.SLOT.acquire()
        try:
            with self.assertRaises(HTTPError) as raised:
                self.request({"query": "京都"})
            self.assertEqual(raised.exception.code, 429)
        finally:
            server.SLOT.release()


if __name__ == "__main__":
    unittest.main()
