"""Offline fixed-provider, billing, model routing and isolated child checks."""
import copy
import json
import multiprocessing
import threading
import time
import unittest
from unittest.mock import patch

import byok
from byok import ByokError, ModelSession
from byok_pipeline import FetchBudget, bounded_byok
import timeline as t

KEY = "AIza" + "x" * 35
SCHEMA = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}


def response(value=None, **extra):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(value or {"word": "発明"})}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 10, "totalTokenCount": 40}, **extra}


def slow_byok_child(query, key, options, connection):
    connection.send({"kind": "usage", "usage": {"calls": 1}})
    time.sleep(20)


def completed_byok_child(query, key, options, connection):
    connection.send({"kind": "result", "events": ["fake"]})
    connection.send({"kind": "usage", "usage": {"calls": 2}})
    connection.close()


class ModelTests(unittest.TestCase):
    def session(self, **overrides):
        return ModelSession(KEY, threading.Event(), **{
            "max_cost_microusd": 500_000, "max_calls": 5, "input_bytes": 100_000,
            "output_tokens": 3000, "min_call_interval": 0, "send": lambda *_: response(), **overrides})

    def call(self, session, schema=SCHEMA):
        return session("JSONで回答", "テーマ", time.monotonic() + 30, schema)

    def test_fixed_payload_usage_schema_and_key_not_in_payload(self):
        observed = []
        session = self.session(send=lambda key, payload, timeout: observed.append((key, payload, timeout)) or response())
        before = copy.deepcopy(SCHEMA)
        self.assertEqual(self.call(session), {"word": "発明"})
        key, payload, timeout = observed[0]
        self.assertEqual(key, KEY)
        self.assertNotIn(KEY.encode(), payload)
        data = json.loads(payload)
        self.assertEqual(byok.MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(data["generationConfig"]["responseJsonSchema"]["additionalProperties"], False)
        self.assertEqual(SCHEMA, before)
        self.assertNotIn("tools", data)
        self.assertEqual(data["generationConfig"]["thinkingConfig"],
                         {"thinkingLevel": "minimal", "includeThoughts": False})
        self.assertNotIn("temperature", data["generationConfig"])
        self.assertEqual(session.summary()["cost_microusd"], 34)
        self.assertFalse(session.summary()["cost_is_upper_bound"])
        self.assertEqual(session.summary()["calls_by_stage"], {"other": 1})
        self.assertEqual(session.summary()["request_bytes_by_stage"], {"other": len(payload)})
        self.assertNotIn(KEY, repr(session.summary()))
        session.close()
        self.assertIsNone(session._key)

    def test_cost_input_and_call_caps_prevent_dispatch(self):
        for config, expected in (({"max_cost_microusd": 1}, "cost_budget"),
                                  ({"input_bytes": 1}, "input_budget")):
            sends = []
            session = self.session(send=lambda *_: sends.append(1), **config)
            with self.assertRaisesRegex(ByokError, expected):
                self.call(session)
            self.assertEqual(sends, [])
        session = self.session(max_calls=1)
        self.call(session)
        with self.assertRaisesRegex(ByokError, "call_budget"):
            self.call(session)
        self.assertEqual(session.summary()["calls"], 1)

    def test_google_key_only_and_thinking_tokens_are_charged(self):
        byok.validate_key(KEY)
        for key in ("sk-ant-" + "x" * 40, KEY + "\n", KEY + "?key=x", "https://example.com"):
            with self.assertRaisesRegex(ByokError, "invalid_api_key"):
                byok.validate_key(key)
        session = self.session(send=lambda *_: response(usageMetadata={
            "promptTokenCount": 30, "candidatesTokenCount": 10,
            "thoughtsTokenCount": 7, "totalTokenCount": 47, "cachedContentTokenCount": 20}))
        self.call(session)
        self.assertEqual(session.summary()["output_tokens"], 17)
        self.assertEqual(session.summary()["cost_microusd"], 52)

    def test_uncertain_usage_keeps_full_reservation_and_no_retry(self):
        observed = []
        session = self.session(send=lambda *_: observed.append(1) or response(usageMetadata={}))
        with self.assertRaisesRegex(ByokError, "provider_usage"):
            self.call(session)
        self.assertTrue(session.summary()["cost_is_upper_bound"])
        self.assertGreaterEqual(session.summary()["cost_microusd"], byok.token_cost(0, byok.THINKING_BOUND + 3000))
        with self.assertRaisesRegex(ByokError, "provider_usage"):
            self.call(session)
        self.assertEqual(observed, [1])

    def test_call_spacing_and_cancel_or_deadline_do_not_dispatch_or_reserve(self):
        class FakeEvent:
            now = 0
            cancelled = False
            cancel_on_wait = False
            def is_set(self):
                return self.cancelled
            def wait(self, seconds):
                self.now += seconds
                if self.cancel_on_wait:
                    self.cancelled = True
        event, starts = FakeEvent(), []
        session = self.session(min_call_interval=15, clock=lambda: event.now,
            send=lambda *_: starts.append(event.now) or response())
        session.stopping = event
        for _ in range(3):
            session("system", "prompt", 120, SCHEMA)
        self.assertEqual(starts, [0, 15, 30])
        before = session.summary()
        with self.assertRaisesRegex(ByokError, "time_limit"):
            session("system", "prompt", 40, SCHEMA)
        self.assertEqual(session.summary(), before)
        self.assertEqual(len(starts), 3)
        event = FakeEvent()
        session = self.session(min_call_interval=15, clock=lambda: event.now)
        session.stopping = event
        session("system", "prompt", 120, SCHEMA)
        before = session.summary()
        event.cancel_on_wait = True
        with self.assertRaisesRegex(ByokError, "cancelled"):
            session("system", "prompt", 120, SCHEMA)
        self.assertEqual(session.summary(), before)

    def test_quota_errors_are_classified_without_secret_or_raw_error(self):
        from unittest.mock import Mock
        def body(*identifiers):
            return json.dumps({"error": {"message": KEY, "details": [{
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": value, "description": KEY} for value in identifiers]}]}}).encode()
        for raw, expected in ((body("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), "provider_daily"),
                              (body("GenerateContentInputTokensPerMinutePerModel-FreeTier"), "provider_tokens"),
                              (body("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), "provider_rate"),
                              (body("RequestsPerDay", "TokensPerMinute"), "provider_daily"),
                              (b"bad" + KEY.encode(), "provider_rate"),
                              (b"x" * (byok.MAX_ERROR_RESPONSE + 1), "provider_rate")):
            connection = Mock()
            connection.getresponse.return_value.status = 429
            connection.getresponse.return_value.read.return_value = raw
            with patch.object(byok.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaisesRegex(ByokError, expected) as error:
                    byok.transport(KEY, b"{}", 5)
            self.assertNotIn(KEY, repr(error.exception))
            self.assertIsNone(error.exception.__cause__)
            connection.request.assert_called_once()
            connection.getresponse.return_value.read.assert_called_once_with(byok.MAX_ERROR_RESPONSE + 1)
            connection.close.assert_called_once()

    def test_input_token_window_waits_until_old_usage_expires(self):
        class FakeEvent:
            now = 0
            def is_set(self):
                return False
            def wait(self, seconds):
                self.now += seconds
        event, starts, reservations = FakeEvent(), [], []
        def send(*_):
            starts.append(event.now)
            reservations.append(sum(count for _, count in session.input_window))
            return response(usageMetadata={"promptTokenCount": 95000,
                "candidatesTokenCount": 10, "totalTokenCount": 95010})
        session = self.session(min_call_interval=15, clock=lambda: event.now, send=send)
        session.stopping = event
        for _ in range(3):
            session("system", "x" * 95000, 120, SCHEMA)
        self.assertEqual(starts, [0, 15, 60])
        self.assertTrue(all(n <= byok.INPUT_TOKENS_PER_MINUTE for n in reservations))

    def test_failure_latches_no_paid_retry_or_secret_error(self):
        for data in (response(candidates=[]),
                     response(candidates=[{"finishReason": "MAX_TOKENS"}]),
                     response({"unknown": "field"}), response({"word": 123}),
                     response(candidates=[{"finishReason": "STOP", "content": {"parts": [{"text": KEY}]}}]),
                     response(usageMetadata={}),
                     response(usageMetadata={"promptTokenCount": 999999, "candidatesTokenCount": 1, "totalTokenCount": 1000000})):
            sends = []
            session = self.session(send=lambda *_: sends.append(1) or data)
            for _ in range(2):
                with self.assertRaises(ByokError) as caught:
                    self.call(session)
                self.assertNotIn(KEY, repr(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
            self.assertEqual(len(sends), 1)
            self.assertIsNone(session._key)

    def test_cancel_during_dispatch_does_not_start_next_call(self):
        session = self.session()
        def send(*_):
            session.stopping.set()
            return response()
        session.send = send
        with self.assertRaisesRegex(ByokError, "cancelled"):
            self.call(session)
        self.assertEqual(session.summary()["calls"], 1)
        self.assertEqual(session.summary()["cost_microusd"], 34)
        with self.assertRaisesRegex(ByokError, "cancelled"):
            self.call(session)

    def test_parallel_calls_share_atomic_cap(self):
        from concurrent.futures import ThreadPoolExecutor
        session = self.session(max_calls=1)
        def run(_):
            try:
                self.call(session)
                return True
            except ByokError:
                return False
        with ThreadPoolExecutor(5) as pool:
            self.assertEqual(sum(pool.map(run, range(5))), 1)

    def test_transport_rejects_redirect_without_following_or_reading_body(self):
        from unittest.mock import Mock
        connection = Mock()
        connection.getresponse.return_value.status = 302
        with patch.object(byok.http.client, "HTTPSConnection", return_value=connection) as factory:
            with self.assertRaisesRegex(ByokError, "provider_unavailable"):
                byok.transport(KEY, b"{}", 5)
        factory.assert_called_once_with("generativelanguage.googleapis.com", timeout=5)
        self.assertEqual(connection.request.call_args.args[:2], ("POST", byok.PATH))
        headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual(headers["x-goog-api-key"], KEY)
        self.assertNotIn(KEY, byok.PATH)
        connection.getresponse.return_value.read.assert_not_called()
        connection.close.assert_called_once()

    def test_transport_failure_diagnostics_are_fixed_and_latch_without_retry(self):
        from unittest.mock import Mock
        for failure, kind, status in ((None, "http", 503),
                                      (TimeoutError(KEY), "timeout", None),
                                      (byok.socket.gaierror(KEY), "dns", None),
                                      (byok.ssl.SSLError(KEY), "tls", None),
                                      (ConnectionResetError(KEY), "connection", None)):
            with self.subTest(kind=kind):
                connection = Mock()
                connection.getresponse.return_value.status = status
                if failure:
                    connection.request.side_effect = failure
                session = self.session(send=byok.transport)
                with patch.object(byok.http.client, "HTTPSConnection", return_value=connection) as factory:
                    with self.assertRaisesRegex(ByokError, "provider_unavailable"):
                        self.call(session)
                    detail = session.summary()["failure_detail"]
                    self.assertEqual(detail, {"stage": "other", "kind": kind, "http_status": status})
                    with self.assertRaisesRegex(ByokError, "provider_unavailable"):
                        self.call(session)
                    self.assertEqual(session.summary()["failure_detail"], detail)
                factory.assert_called_once()
                connection.getresponse.return_value.read.assert_not_called()
                connection.close.assert_called_once()
                self.assertNotIn(KEY, repr(session.summary()))

    def test_error_diagnostic_rejects_arbitrary_text(self):
        for value in (KEY, {}, [], True):
            error = ByokError("provider_unavailable", http_status=value, failure_kind=value)
            self.assertIsNone(error.http_status)
            self.assertIsNone(error.failure_kind)

    def test_every_schema_routes_to_byok_without_operator_call(self):
        calls = []
        def model(system, prompt, deadline, schema):
            calls.append(schema)
            if schema is t.KIND_SCHEMA:
                return {"word": "発明", "subject": "技術"}
            if schema is t.RELATED_SCHEMA:
                return {"judgments": []}
            if schema is t.PRUNE_SCHEMA:
                return {"ratings": []}
            if schema is t.EVENT_SCHEMA:
                return {"events": [], "theme": "テスト"}
            return {"supported": [0], "rejected": []}
        query = t.parse_query("テスト")
        source = {"url": "https://ja.wikipedia.org/wiki/Test", "title": "資料", "text": "1900年に技術が公開された。"}
        event = {"year": 1900, "date": "1900年", "title": "公開", "description": "技術が公開された。",
                 "quote": "1900年に技術が公開された。", "source": source}
        with patch.object(t, "model_json", side_effect=AssertionError("Operator model used")), \
             patch.object(t, "crosscheck_sources", return_value=[]):
            t.event_kind_word(query, time.monotonic() + 30, model=model)
            t.related_sources(query, [source, source], time.monotonic() + 30, [], model=model)
            t.prune_events(query, [event] * 51, [], time.monotonic() + 30, [], model=model)
            t.generate_batch(query, [source], time.monotonic() + 30, model=model)
            t.verify_batch(query, [source], lambda _: None, time.monotonic() + 30, [],
                           {"proposals": [], "valid": [event], "reasons": {}, "seconds": 0}, model=model)
        self.assertEqual(calls, [t.KIND_SCHEMA, t.RELATED_SCHEMA, t.PRUNE_SCHEMA, t.EVENT_SCHEMA, t.VERIFY_SCHEMA])

    def test_byok_errors_are_not_swallowed_by_optional_stages(self):
        def failed(*_):
            raise ByokError("cost_budget")
        query = t.parse_query("テスト")
        with self.assertRaisesRegex(ByokError, "cost_budget"):
            t.event_kind_word(query, time.monotonic() + 30, model=failed)

    def test_full_pipeline_routes_generation_thread_and_verification(self):
        calls = []
        source = {"url": "https://ja.wikipedia.org/wiki/Test", "title": "テスト", "text": "1900年にテスト技術が公開された。"}
        def model(system, prompt, deadline, schema):
            calls.append(schema)
            if schema is t.KIND_SCHEMA:
                return {"word": "発明", "subject": "技術"}
            if schema is t.RELATED_SCHEMA:
                return {"judgments": []}
            if schema is t.EVENT_SCHEMA:
                return {"theme": "テスト", "events": [{"year": 1900, "date": "1900年", "title": "テスト技術の公開",
                    "description": "テスト技術が公開された。", "source_id": 1,
                    "quote": source["text"], "check_query": "Test technology"}]}
            return {"supported": [0], "rejected": []}
        def search(query, deadline, *, model):
            t.event_kind_word(query, deadline, model=model)
            return [source, {**source, "url": "https://en.wikipedia.org/wiki/Test"}]
        with patch.object(t, "model_json", side_effect=AssertionError("Operator model used")), \
             patch.object(t, "SOURCE", "wikipedia"), patch.object(t, "SOURCE_FILTER", "model"), \
             patch.object(t, "search", side_effect=search), patch.object(t, "fetch_sources", return_value=[source]), \
             patch.object(t, "material_batches", return_value=[[source]]), patch.object(t, "crosscheck_sources", return_value=[]):
            result = t.build_timeline(t.parse_query("テスト"), lambda _: None, model=model)
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(calls, [t.KIND_SCHEMA, t.RELATED_SCHEMA, t.EVENT_SCHEMA, t.VERIFY_SCHEMA])


class PipelineTests(unittest.TestCase):
    def test_retrieval_call_byte_and_fixed_route_budgets(self):
        budget = FetchBudget(1, 10)
        def read(reader, url, limit):
            self.assertEqual(limit, 10)
            return 200, {}, b"12345", url
        budget.article(read, None, "https://ja.wikipedia.org/wiki/Test")
        self.assertEqual(budget.bytes, 5)
        with self.assertRaisesRegex(ByokError, "fetch_budget"):
            budget.article(read, None, "https://ja.wikipedia.org/wiki/Test")
        for url in ("http://127.0.0.1/", "https://evil.example/wiki/X", "https://api.anthropic.com/v1/messages"):
            with self.assertRaisesRegex(ByokError, "fetch_route"):
                FetchBudget(1, 10).check(url)
        budget = FetchBudget(5, 3)
        def too_large(*_):
            raise t.TimelineError("出典ページが大きすぎます。")
        with self.assertRaisesRegex(ByokError, "fetch_budget"):
            budget.article(too_large, None, "https://en.wikipedia.org/wiki/Test")

    def test_isolated_child_ends_and_drains_usage(self):
        records = []
        bounded_byok("test", KEY, {"time_limit": 3}, records.append, threading.Event(), child=completed_byok_child)
        self.assertEqual([r["kind"] for r in records], ["usage", "result", "ended"])

    def test_cancel_and_timeout_terminate_child(self):
        before = {p.pid for p in multiprocessing.active_children()}
        stopped = threading.Event()
        timer = threading.Timer(0.25, stopped.set)
        timer.start()
        start = time.monotonic()
        bounded_byok("test", KEY, {"time_limit": 10}, lambda _: None, stopped, child=slow_byok_child)
        timer.join()
        self.assertLess(time.monotonic() - start, 3)
        records = []
        bounded_byok("test", KEY, {"time_limit": 0.25}, records.append, threading.Event(), child=slow_byok_child)
        self.assertEqual(records[-1], {"kind": "ended", "error": "time_limit"})
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before)


if __name__ == "__main__":
    unittest.main()
