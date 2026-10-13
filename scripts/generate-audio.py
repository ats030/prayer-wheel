#!/usr/bin/env python3
"""Generate static WAVs using a verified, local VOICEVOX Nemo engine (stdlib only)."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION = "0.24.0"
SPEAKER_ID = 10001
SPEAKER_UUID = "2171909e-d2d1-4bbb-aa45-442c12732665"
SETTINGS = {"speedScale": 0.85, "intonationScale": 0.65,
            "prePhonemeLength": 0.1, "postPhonemeLength": 0.25,
            "outputSamplingRate": 24000, "outputStereo": False}


def request(host, path, body=None):
    req = urllib.request.Request(host + path, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def generate(host, sample):
    manifest = json.loads(request(host, "/engine_manifest"))
    version = json.loads(request(host, "/version"))
    if manifest.get("uuid") != "208cf94d-43d2-4cf5-abc0-9783cac36d29" or version != ENGINE_VERSION:
        raise ValueError("Use VOICEVOX Nemo Engine 0.24.0; refusing a different engine")
    speakers = json.loads(request(host, "/speakers"))
    voice = next(s for s in speakers if s["speaker_uuid"] == SPEAKER_UUID)
    if not any(s["id"] == SPEAKER_ID for s in voice["styles"]):
        raise ValueError("Nemo 男声1 style ID does not match")
    raw = (ROOT / "data/sutra.json").read_bytes()
    sutra = json.loads(raw)
    output = ROOT / "audio"
    output.mkdir(exist_ok=True)
    records = []
    for i, chunk in enumerate(sutra["chunks"]):
        if sample and i != 1:
            continue
        params = urllib.parse.urlencode({"speaker": SPEAKER_ID, "text": chunk["reading"]})
        query = json.loads(request(host, "/audio_query?" + params, b""))
        query.update(SETTINGS)
        wav = request(host, f"/synthesis?speaker={SPEAKER_ID}&enable_interrogative_upspeak=false",
                      json.dumps(query).encode())
        with wave.open(io.BytesIO(wav)) as reader:
            duration = reader.getnframes() / reader.getframerate()
            if reader.getnchannels() != 1 or reader.getframerate() != 24000 or duration <= 0:
                raise ValueError("Unexpected WAV format")
        name = f"{i + 1:02d}.wav"
        (output / name).write_bytes(wav)
        # Keep the engine's phonetic output so input readings can be audited.
        records.append({"file": name, "seconds": round(duration, 3),
                        "sha256": hashlib.sha256(wav).hexdigest(), "kana": query["kana"]})
        print(f"{name}: {duration:.2f}s / {query['kana']}", flush=True)
    metadata = {"engine": manifest["name"], "engineVersion": ENGINE_VERSION,
                "voice": voice["name"], "voiceVersion": voice["version"],
                "speakerId": SPEAKER_ID, "speakerUuid": SPEAKER_UUID,
                "credit": "VOICEVOX Nemo", "settings": SETTINGS,
                "sutraSha256": hashlib.sha256(raw).hexdigest(), "files": records}
    (output / ("sample.json" if sample else "manifest.json")).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="http://127.0.0.1:50121")
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    generate(args.engine.rstrip("/"), args.sample)
