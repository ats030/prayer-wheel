#!/usr/bin/env python3
"""Check sample provenance, intact baseline PCM, WAV signal and generation controls."""
import array
import hashlib
import io
import json
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'audition/manifest.json').read_text())
raw = (ROOT / 'data/sutra.json').read_bytes()
assert manifest['sutraSha256'] == hashlib.sha256(raw).hexdigest()
assert manifest['engineVersion'] == '0.24.0' and manifest['speakerId'] == 10001
assert [s['section'] for s in manifest['sections']] == list(range(2, 7))
assert [s['text'] for s in manifest['sections']] == [s['text'] for s in json.loads(raw)['chunks'][1:6]]
shipped = json.loads((ROOT / 'audition/baseline/manifest.json').read_text())
baseline = b''
for section in manifest['sections']:
    original = (ROOT / 'audition/baseline' / f"{section['section']:02d}.wav").read_bytes()
    assert hashlib.sha256(original).hexdigest() == section['currentSha256']
    with wave.open(io.BytesIO(original)) as wav:
        baseline += wav.readframes(wav.getnframes())
    query = section['query']
    assert section['reading'] == json.loads(raw)['chunks'][section['section'] - 1]['reading']
    assert query['kana'] == shipped['files'][section['section'] - 1]['kana'], 'Pronunciation boundaries changed'
    assert all(query[k] == v for k, v in manifest['settings'].items())
    for phrase in query['accent_phrases']:
        if phrase.get('pause_mora'):
            assert phrase['pause_mora']['vowel_length'] == .04
        assert all(.07 <= m['vowel_length'] <= .18 for m in phrase['moras'] if m['pitch'] > 0)
for entry in manifest['files']:
    path = ROOT / 'audition' / entry['file']
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry['sha256']
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert abs(wav.getnframes() / 24000 - entry['seconds']) < .001
        pcm = wav.readframes(wav.getnframes())
        samples = array.array('h', pcm)
        assert 100 < max(abs(v) for v in samples) < 32767
        if entry['file'] == 'current.wav':
            assert pcm == baseline, 'Baseline no longer matches archived Nemo audio'
print('Verified A/B audio hashes, five sections, baseline PCM, timing controls and unclipped signal')
