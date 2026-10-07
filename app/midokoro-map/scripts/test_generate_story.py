#!/usr/bin/env python3
"""Meaningful failure and transport checks, without requiring an LLM."""
import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("story_writer", HERE / "generate-story.py")
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


def fixture():
    packet = json.loads((HERE.parent / "docs/story-packets/kusatsu-yumomi.json").read_text())
    facts = {f["id"]: f for f in packet["facts"]}
    draft = {"error": "", "title": packet["title"], "lead": "熱い湯を扱う町の工夫をたどります。",
             "intro": "湯畑と浴場を結ぶ地図です。", "reading_title": "湯の仕事と源泉",
             "places": [], "relations": [], "questions": []}
    for kind in ("places", "relations"):
        for item in packet[kind]:
            body = " ".join(facts[f]["text"] for f in item["fact_ids"])
            while len(body) < 80:
                body += "その場所を、湯の扱い方と源泉という視点から見比べられます。"
            row = {"id": item["id"], "body": body,
                   "evidence_ids": item["fact_ids"][:]}
            if kind == "relations":
                row["title"] = "湯の扱い方を見比べる"
            draft[kind].append(row)
    draft["questions"] = [{"relation_id": r["id"], "label": "湯はどうつながる？"} for r in packet["relations"][:3]]
    return packet, draft


class WriterChecks(unittest.TestCase):
    def setUp(self):
        self.packet, self.draft = fixture()

    def test_missing_evidence_abstains_before_http(self):
        self.packet["places"][0]["fact_ids"] = []
        with tempfile.TemporaryDirectory() as temp:
            packet = Path(temp) / "input.json"
            packet.write_text(json.dumps(self.packet))
            with patch.object(writer, "request_json") as api:
                with self.assertRaises(writer.StoryError):
                    writer.generate(packet, Path(temp) / "out", "http://localhost:11434", "gemma4:12b")
                api.assert_not_called()

    def test_unknown_and_misattributed_evidence_are_rejected(self):
        for evidence in [["made-up"], ["ohtakinoyu-facts"]]:
            with self.subTest(evidence=evidence):
                self.draft["places"][0]["evidence_ids"] = evidence
                with self.assertRaises(writer.StoryError):
                    writer.validate_draft(self.draft, self.packet)

    def test_invented_year_is_rejected(self):
        self.draft["relations"][0]["body"] += "1900年に始まりました。"
        with self.assertRaisesRegex(writer.StoryError, "数字"):
            writer.validate_draft(self.draft, self.packet)

    def test_invalid_coordinates_and_reserved_dom_ids(self):
        for field, value in [("lat", float("nan")), ("lng", 181), ("id", "places")]:
            with self.subTest(field=field):
                packet = copy.deepcopy(self.packet)
                packet["places"][0][field] = value
                with self.assertRaises(writer.StoryError):
                    writer.validate_packet(packet)

    def test_source_urls_cannot_be_executable(self):
        self.packet["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(writer.StoryError):
            writer.validate_packet(self.packet)

    def test_duplicate_rows_and_questions_are_rejected(self):
        bad = copy.deepcopy(self.draft)
        bad["places"][1]["id"] = bad["places"][0]["id"]
        with self.assertRaises(writer.StoryError):
            writer.validate_draft(bad, self.packet)
        self.draft["questions"][1]["relation_id"] = self.draft["questions"][0]["relation_id"]
        with self.assertRaises(writer.StoryError):
            writer.validate_draft(self.draft, self.packet)

    def test_model_abstention_is_not_a_draft(self):
        self.draft["error"] = "資料不足"
        with self.assertRaisesRegex(writer.StoryError, "資料不足"):
            writer.validate_draft(self.draft, self.packet)

    def test_short_body_and_extra_fields_are_rejected(self):
        bad = copy.deepcopy(self.draft)
        bad["places"][0]["body"] = "湯畑の湯は冷めます。"
        with self.assertRaisesRegex(writer.StoryError, "80文字"):
            writer.validate_draft(bad, self.packet)
        self.draft["relations"][0]["url"] = "https://unknown.example/"
        with self.assertRaisesRegex(writer.StoryError, "schema"):
            writer.validate_draft(self.draft, self.packet)

    def test_observed_typo_and_misleading_phrase_are_rejected(self):
        self.packet["forbidden_phrases"] = ["祭領", "組み合わせて使用"]
        for phrase in self.packet["forbidden_phrases"]:
            with self.subTest(phrase=phrase):
                bad = copy.deepcopy(self.draft)
                bad["intro"] = phrase
                with self.assertRaisesRegex(writer.StoryError, "禁止表現"):
                    writer.validate_draft(bad, self.packet)

    def test_html_is_escaped_and_editorial_notes_are_fixed(self):
        self.draft["lead"] = '<script>alert("x")</script>'
        rendered = writer.render(self.draft, self.packet)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn('<script>alert("x")', rendered)
        self.assertIn(self.packet["relations"][0]["note"], rendered)
        self.assertIn('data-story-preview="true"', rendered)
        self.assertIn('name="robots" content="noindex,nofollow"', rendered)

    def test_typo_restoration_is_source_bounded_and_does_not_mutate_raw_draft(self):
        bad = copy.deepcopy(self.draft)
        bad["intro"] = "祭領を奨領した町です。"
        unchanged, changes = writer.normalize_known_typos(bad, self.packet)
        self.assertEqual(unchanged["intro"], bad["intro"])
        self.assertFalse(changes)
        self.packet["facts"][0]["text"] += "祭礼を奨励した。"
        fixed, changes = writer.normalize_known_typos(bad, self.packet)
        self.assertEqual(fixed["intro"], "祭礼を奨励した町です。")
        self.assertEqual(len(changes), 2)
        self.assertEqual(bad["intro"], "祭領を奨領した町です。")

    def test_recheck_reuses_response_without_generation_and_checks_packet_digest(self):
        source = HERE.parent / "docs/story-packets/kusatsu-yumomi.json"
        saved = {"status": "rejected", "packet": self.packet, "requested_model": "gemma4:12b",
                 "model_digest": "abc", "prompt_version": "old-prompt",
                 "response": {"done": True, "done_reason": "stop", "model": "gemma4:12b",
                              "message": {"content": json.dumps(self.draft, ensure_ascii=False)}}}
        with tempfile.TemporaryDirectory() as temp:
            response = Path(temp) / "failed.json"
            response.write_text(json.dumps(saved))
            with patch.object(writer, "request_json", return_value={"models": [{"name": "gemma4:12b", "digest": "abc"}]}) as api:
                manifest = writer.generate(source, Path(temp) / "out", "http://localhost:11434", "gemma4:12b", recheck=response)
                self.assertEqual([call.args[1] for call in api.call_args_list], ["/api/tags"])
                self.assertEqual(manifest["generation_mode"], "recheck")
                self.assertEqual(manifest["original_prompt_version"], "old-prompt")
                self.assertIsNone(manifest["request_sha256"])
                self.assertIsNone(manifest["options"])
                saved["model_digest"] = "wrong"
                response.write_text(json.dumps(saved))
                with self.assertRaisesRegex(writer.StoryError, "digest"):
                    writer.generate(source, Path(temp) / "bad", "http://localhost:11434", "gemma4:12b", recheck=response)

    def test_public_output_and_existing_runs_are_refused_before_http(self):
        source = HERE.parent / "docs/story-packets/kusatsu-yumomi.json"
        with patch.object(writer, "request_json") as api:
            for output in [HERE.parent / "frontend/stories/new-draft", HERE.parent]:
                with self.assertRaises(writer.StoryError):
                    writer.generate(source, output, "http://localhost:11434", "gemma4:12b")
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(writer.StoryError):
                    writer.generate(source, Path(temp), "http://localhost:11434", "gemma4:12b")
            api.assert_not_called()

    def test_failures_do_not_emit_preview(self):
        responses = [
            {"done": True, "done_reason": "length", "model": "gemma4:12b"},
            {"done": True, "done_reason": "stop", "model": "other"},
            {"done": True, "done_reason": "stop", "model": "gemma4:12b", "message": {"content": "bad JSON"}},
        ]
        for response in responses:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / "out"
                with patch.object(writer, "request_json", side_effect=[
                    {"models": [{"name": "gemma4:12b", "digest": "abc"}]}, response]):
                    with self.assertRaises(writer.StoryError):
                        writer.generate(HERE.parent / "docs/story-packets/kusatsu-yumomi.json", out,
                                        "http://localhost:11434", "gemma4:12b")
                self.assertFalse(out.exists())
                rejected = json.loads(out.with_name("out.failed.json").read_text())
                self.assertEqual(rejected["status"], "rejected")
                self.assertEqual(rejected["response"], response)

    def test_http_contract_and_complete_preview_bundle(self):
        calls = []
        draft = self.draft
        class API(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                calls.append((self.path, None, dict(self.headers)))
                self.answer({"models": [{"name": "gemma4:12b", "digest": "tested-digest"}]})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append((self.path, data, dict(self.headers)))
                self.answer({"done": True, "done_reason": "stop", "model": "gemma4:12b",
                             "message": {"content": json.dumps(draft, ensure_ascii=False)}, "eval_count": 123})

            def answer(self, value):
                content = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        server = ThreadingHTTPServer(("127.0.0.1", 0), API)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / "out"
                source = Path(temp) / "unformatted-input.json"
                source.write_text(json.dumps(self.packet, ensure_ascii=False, separators=(",", ":")))
                manifest = writer.generate(source, out,
                                           f"http://127.0.0.1:{server.server_port}", "gemma4:12b")
                self.assertEqual([x[0] for x in calls], ["/api/tags", "/api/chat"])
                payload = calls[1][1]
                self.assertFalse(payload["stream"])
                self.assertFalse(payload["think"])
                self.assertEqual(payload["format"]["type"], "object")
                self.assertEqual(calls[1][2]["X-Client-App"], "midokoro-story-writer")
                self.assertNotIn("X-Ollama-Workload-Class", calls[1][2])
                self.assertEqual(manifest["model_digest"], "tested-digest")
                self.assertEqual(manifest["editorial_review"], "pending")
                self.assertEqual(manifest["eval_count"], 123)
                self.assertEqual((out / "packet.json").read_bytes(), source.read_bytes())
                self.assertEqual(manifest["packet_sha256"], hashlib.sha256((out / "packet.json").read_bytes()).hexdigest())
                self.assertTrue((out / "review.md").is_file())
                self.assertTrue((out / "preview/stories/kusatsu-yumomi/index.html").is_file())
                self.assertTrue((out / "preview/vendor/leaflet.js").is_file())
                self.assertIn("storyPreview", (out / "preview/stories/story.js").read_text())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
