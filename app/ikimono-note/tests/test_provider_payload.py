"""Cross-language payload parity without contacting an AI provider."""
import base64
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import vision


def run_browser(cases):
    node = shutil.which("node")
    assert node, "Node is required for browser payload parity validation"
    script = """
      import {assembleProviderPayload} from './static/assets/provider-payload.mjs';
      let input = '';
      for await (const chunk of process.stdin) input += chunk;
      const results = JSON.parse(input).map(({provider, template, images}) => {
        const before = JSON.stringify(template);
        try {
          const payload = assembleProviderPayload(provider, template, images);
          return {payload, unchanged: before === JSON.stringify(template)};
        } catch (error) {return {error: error.name};}
      });
      process.stdout.write(JSON.stringify(results));
    """
    result = subprocess.run(
        [node, "--input-type=module", "-e", script], cwd=APP,
        input=json.dumps(cases), text=True, capture_output=True, timeout=30, check=True,
    )
    return json.loads(result.stdout)


def test_browser_payload_matches_all_provider_requests():
    cases, expected = [], []
    for provider in ("openai", "anthropic", "gemini"):
        for count in (1, 3):
            images = [base64.b64encode(bytes([255, 216, index, 255, 217])).decode("ascii") for index in range(count)]
            for context in ({}, {"location": "東京都\n山麓", "observed_date": "2026-10-09", "size": "約5cm"}):
                cases.append({
                    "provider": provider,
                    "template": vision.provider_payload(provider, "selected-model", [], **context),
                    "images": images,
                })
                expected.append(vision.provider_payload(provider, "selected-model", images, **context))
    results = run_browser(cases)
    assert [result["payload"] for result in results] == expected
    assert all(result["unchanged"] for result in results)


def test_browser_rejects_unsupported_or_stale_templates_and_bad_counts():
    cases = [{"provider": provider, "template": {}, "images": ["AA=="]}
             for provider in ("openai", "anthropic", "gemini", "local", "unknown")]
    for provider in ("openai", "anthropic", "gemini"):
        for images in ([], ["AA=="] * 4, [""], [None], "AA=="):
            cases.append({"provider": provider,
                          "template": vision.provider_payload(provider, "model", []), "images": images})
        # A populated template cannot silently duplicate or replace images.
        cases.append({"provider": provider,
                      "template": vision.provider_payload(provider, "model", ["AA=="]), "images": ["AA=="]})
    assert all(result == {"error": "TypeError"} for result in run_browser(cases))


def test_payload_templates_do_not_share_mutable_settings():
    original_schema = json.loads(json.dumps(vision.GEMINI_RESPONSE_SCHEMA))
    first = vision.provider_payload("gemini", "model", [])
    # The template may leave the process through a response or an FFI adapter.
    first["generationConfig"]["responseSchema"]["type"] = "altered"
    assert vision.provider_payload("gemini", "model", [])["generationConfig"]["responseSchema"] == original_schema


def test_unknown_provider_fails_closed():
    with pytest.raises(vision.VisionError):
        vision.provider_payload("local", "model", [])
