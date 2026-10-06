#!/usr/bin/env python3
"""Regression checks for pagination, privacy, replacement, gaps and failure isolation."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("visit-log") / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load("cloud_collector", "fetch-cloud-run-logs.py")
web = load("visit_main", "main.py")
CONFIG = {"projects": ["p"], "exclude": [], "api_prefixes": ["/api"], "static_prefixes": ["/assets"]}
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def entry(path="/", at="2026-10-06T11:00:00Z", status=200, ua="browser", method="GET"):
    return {"timestamp": at, "httpRequest": {"requestUrl": "https://example.test" + path,
            "status": status, "userAgent": ua, "requestMethod": method, "remoteIp": "192.0.2.1"},
            "insertId": "private-id"}


class FakeGoogle:
    fail = False
    entries_data = [entry("/?token=secret"), entry("/api/x", status=500), entry("/assets/a.css", ua="Googlebot")]

    def services(self, project):
        return [{"name": f"projects/{project}/locations/r/services/s", "uri": "https://example.test"}]

    def retention(self, project):
        return 30

    def entries(self, *args):
        if self.fail:
            yield entry("/partial")
            raise RuntimeError("failed after first page")
        start, end = args[-2:]
        yield from (r for r in self.entries_data if start <= collector.parse(r["timestamp"]) < end)


class CloudTests(unittest.TestCase):
    def test_privacy_jst_and_classification(self):
        rows = collector.aggregate([entry("/a?token=secret#fragment", at="2026-10-05T16:00:00Z"),
                                    entry("/api/x", status=404), entry("/a.png", ua="crawler"),
                                    entry("/submit", method="POST")], CONFIG)
        self.assertEqual({r["date"] for r in rows}, {"2026-10-06"})
        self.assertEqual({r["kind"] for r in rows}, {"page", "api", "static"})
        raw = json.dumps(rows)
        for private in ("secret", "fragment", "remoteIp", "192.0.2.1", "userAgent", "crawler", "private-id"):
            self.assertNotIn(private, raw)

    def test_pagination_including_empty_page(self):
        google = object.__new__(collector.Google)
        pages = iter([{"nextPageToken": "a"}, {"entries": [entry()], "nextPageToken": "b"}, {"entries": [entry("/x")]}])
        calls = []
        def request(url, body):
            calls.append(dict(body))
            return next(pages)
        google.request = request
        rows = list(google.entries("p", "s", "r", NOW - timedelta(days=1), NOW))
        self.assertEqual(len(rows), 2)
        self.assertEqual(calls[1]["pageToken"], "a")
        self.assertIn('resource.labels.location="r"', calls[0]["filter"])

    def test_repeat_failure_recovery_exclusion_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "stats.json"
            google = FakeGoogle()
            first, errors = collector.update(output, CONFIG, google, NOW)
            self.assertFalse(errors)
            second, _ = collector.update(output, CONFIG, google, NOW + timedelta(hours=1))
            self.assertEqual(second["services"][0]["rows"], first["services"][0]["rows"])
            google.fail = True
            failed, errors = collector.update(output, CONFIG, google, NOW + timedelta(hours=2))
            self.assertTrue(errors)
            self.assertEqual(failed["services"][0]["rows"], second["services"][0]["rows"])
            self.assertEqual(failed["services"][0]["observed_at"], second["services"][0]["observed_at"])
            google.fail = False
            google.entries_data = [entry("/fixed", status=201)]
            recovered, _ = collector.update(output, CONFIG, google, NOW + timedelta(hours=3))
            self.assertEqual(sum(r["requests"] for r in recovered["services"][0]["rows"]), 1)
            with patch.object(web, "CLOUD_STATS_PATH", output), patch.object(web, "datetime") as clock:
                clock.now.return_value = NOW.astimezone(collector.TZ)
                clock.fromisoformat.side_effect = datetime.fromisoformat
                summary = web.cloud_summary(90, False)
            service = summary["services"][0]
            self.assertIsNone(service["daily"][0]["requests"])
            self.assertEqual(service["daily"][-1]["coverage"], "partial")
            self.assertEqual(service["requests"], 1)
            excluded, _ = collector.update(output, {**CONFIG, "exclude": ["p/r/s"]}, google, NOW)
            self.assertEqual(excluded["services"], [])

    def test_gap_coverage(self):
        spans = collector.merge_coverage([], NOW - timedelta(days=70), NOW - timedelta(days=40), "2026-07-09")
        spans = collector.merge_coverage(spans, NOW - timedelta(days=30), NOW, "2026-07-09")
        self.assertEqual(len(spans), 2)

    def test_path_identifiers_and_deleted_service_history(self):
        self.assertEqual(collector.safe_path("https://x.test/user/name%40example.com?secret=1"), "/user/:id")
        self.assertEqual(collector.safe_path("/reset/short-token"), "/reset/:id")
        self.assertEqual(collector.safe_path("/items/12345"), "/items/:id")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "stats.json"
            google = FakeGoogle()
            first, _ = collector.update(output, CONFIG, google, NOW)
            google.services = lambda project: []
            google.entries_data = list(google.entries_data) + [entry("/last", at=collector.stamp(NOW))]
            retired, _ = collector.update(output, CONFIG, google, NOW + timedelta(hours=1))
            self.assertEqual(sum(r["requests"] for r in retired["services"][0]["rows"]), 4)
            self.assertEqual(retired["services"][0]["discovery_state"], "retired")
            aged, _ = collector.update(output, CONFIG, google, NOW + timedelta(days=91))
            self.assertEqual(aged["services"], [])

    def test_outage_retention_boundary_preserves_prefix_and_collects_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "stats.json"
            google = FakeGoogle()
            collector.update(output, CONFIG, google, NOW)
            google.entries_data = list(google.entries_data) + [entry("/tail", at=collector.stamp(NOW + timedelta(hours=1)))]
            later = NOW + timedelta(days=29, hours=22)
            state, _ = collector.update(output, CONFIG, google, later)
            self.assertEqual(sum(r["requests"] for r in state["services"][0]["rows"]), 4)
            again, _ = collector.update(output, CONFIG, google, later + timedelta(hours=1))
            self.assertEqual(sum(r["requests"] for r in again["services"][0]["rows"]), 4)

    def test_project_failure_keeps_previous_and_new_project_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "stats.json"
            google = FakeGoogle()
            first, _ = collector.update(output, CONFIG, google, NOW)
            original = google.services
            def services(project):
                if project == "p":
                    raise RuntimeError("permission")
                return original(project)
            google.services = services
            state, errors = collector.update(output, {**CONFIG, "projects": ["p", "q"]}, google, NOW)
            self.assertEqual(errors, ["p"])
            self.assertEqual(len(state["services"]), 2)
            self.assertEqual(state["services"][0]["rows"], first["services"][0]["rows"])
            self.assertEqual(state["services"][1]["status"], "ok")

    def test_api_and_bot_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "stats.json"
            now = datetime.now(timezone.utc)
            at = collector.stamp(now - timedelta(minutes=10))
            google = FakeGoogle()
            google.entries_data = [entry(at=at), entry("/api/x", at=at, status=500), entry("/a.css", at=at, ua="Googlebot")]
            collector.update(output, CONFIG, google, now)
            with patch.object(web, "CLOUD_STATS_PATH", output), patch.object(web, "DATA_DIR", Path(tmp)), patch.object(web, "SITES_PATH", Path(tmp) / "sites.json"):
                client = TestClient(web.app)
                # API remains beacon-compatible and exposes a separate cloud object.
                self.assertEqual(client.get("/api/summary?days=90").status_code, 200)
                normal = client.get("/api/summary?days=90").json()
                bots = client.get("/api/summary?days=90&bots=1").json()
                self.assertEqual(normal["total_views"], 0)
                self.assertEqual(normal["cloud_run"]["services"][0]["requests"], 2)
                self.assertEqual(bots["cloud_run"]["services"][0]["requests"], 3)
                self.assertEqual(normal["cloud_run"]["services"][0]["errors_5xx"], 1)
                self.assertIn("Cloud Run アクセス", client.get("/").text)


if __name__ == "__main__":
    unittest.main()
