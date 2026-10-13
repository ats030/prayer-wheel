#!/usr/bin/env python3
"""Validate the shipped audio against its source and generation manifest."""
import array
import hashlib
import json
from pathlib import Path
import wave

root = Path(__file__).resolve().parents[1]
raw = (root / "data/sutra.json").read_bytes()
sutra = json.loads(raw)
manifest = json.loads((root / "audio/manifest.json").read_text())
assert manifest["sutraSha256"] == hashlib.sha256(raw).hexdigest(), "Stale sutra audio"
assert manifest["engineVersion"] == "0.24.0" and manifest["speakerId"] == 10001
assert len(manifest["files"]) == len(sutra["chunks"])
total = 0
for i, record in enumerate(manifest["files"]):
    assert record["file"] == f"{i + 1:02d}.wav"
    path = root / "audio" / record["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], path
    with wave.open(str(path)) as reader:
        assert reader.getnchannels() == 1 and reader.getsampwidth() == 2 and reader.getframerate() == 24000
        seconds = reader.getnframes() / reader.getframerate()
        assert abs(seconds - record["seconds"]) < .001 and 0.5 < seconds < 20
        samples = array.array("h", reader.readframes(reader.getnframes()))
        peak = max(abs(s) for s in samples)
        assert 100 < peak < 32767, (path, peak)
        assert record["kana"], "Missing pronunciation trace"
        total += seconds
print(f"Verified {len(manifest['files'])} WAVs: {total:.1f}s, matching hashes, no clipping")
