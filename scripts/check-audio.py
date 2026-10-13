#!/usr/bin/env python3
"""Validate all shipped WhiteCUL sections, pronunciation, synthesis trace and WAV signal."""
import array
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import wave

ROOT = Path(__file__).resolve().parents[1]


def check(audio_dir=None):
    audio_dir = Path(audio_dir) if audio_dir else ROOT / 'audio'
    raw = (ROOT / 'data/sutra.json').read_bytes()
    sutra = json.loads(raw)
    manifest = json.loads((audio_dir / 'manifest.json').read_text())
    baseline_raw = (ROOT / 'audition/baseline/manifest.json').read_bytes()
    baseline = json.loads(baseline_raw)
    archived_raw = (ROOT / 'audition/baseline/sutra.json').read_bytes()
    archived = json.loads(archived_raw)
    assert baseline['sutraSha256'] == manifest['sourceSutraSha256'] == hashlib.sha256(archived_raw).hexdigest()
    assert manifest['sutraSha256'] == hashlib.sha256(raw).hexdigest()
    normalize_text = lambda chunks: ''.join(c['text'].replace('　', '') for c in chunks)
    normalize_reading = lambda chunks: re.sub('[、。　 ]', '', ''.join(c['reading'] for c in chunks))
    assert normalize_text(sutra['chunks']) == normalize_text(archived['chunks']), 'Text lost/reordered during split'
    assert normalize_reading(sutra['chunks']) == normalize_reading(archived['chunks']), 'Reading lost/reordered during split'
    normalize_kana = lambda kana: re.sub("[_'/、？]", '', kana)
    assert ''.join(normalize_kana(r['kana']) for r in manifest['files']) == ''.join(normalize_kana(r['kana']) for r in baseline['files']), 'Pronunciation changed during split'
    assert manifest['baselineManifestSha256'] == hashlib.sha256(baseline_raw).hexdigest()
    assert manifest['engineVersion'] == '0.25.2' and manifest['engineUuid'] == '074fc39e-678b-4c13-8916-ffca8d505d1d'
    assert manifest['speakerId'] == 3023 and manifest['speakerUuid'] == '67d5d8da-acd7-4207-bb10-b5542d3a663b'
    assert manifest['teacherId'] == 6000 and manifest['teacherUuid'] == 'b1a81618-b27b-40d2-b0ea-27a9ad408c4b'
    assert manifest['voiceVersion'] == manifest['teacherVersion'] == '0.16.0'
    assert manifest['frameRate'] == 93.75 and manifest['design']['midiKey'] == 55
    assert manifest['design']['effects'] == []
    assert len(manifest['files']) == len(sutra['chunks']) == 56
    assert sutra['audioDirectory'] == 'audio/phrases'
    legacy = json.loads((ROOT / 'audio/legacy-manifest.json').read_text())
    assert len(legacy['files']) == 29 and legacy['speakerId'] == 3023
    for old in legacy['files']:
        assert hashlib.sha256((ROOT / 'audio' / old['file']).read_bytes()).hexdigest() == old['sha256'], 'Old-tab audio changed'
    total = 0
    for index, (record, chunk) in enumerate(zip(manifest['files'], sutra['chunks']), 1):
        assert record['file'] == f'phrases/{index:02d}.wav' and record['section'] == index
        assert record['text'] == chunk['text'] and record['reading'] == chunk['reading']
        assert record['kana'] == record['sourceQuery']['kana']
        moras = [m for p in record['sourceQuery']['accent_phrases'] for m in p['moras']]
        assert ''.join(m['text'] for m in moras) == re.sub("[_'/、？]", '', record['kana'])
        notes = record['score']['notes']
        voiced_notes = [n for n in notes if n['key'] is not None]
        assert [n['lyric'] for n in voiced_notes] == [m['text'] for m in moras]
        assert all(n['key'] == 55 for n in voiced_notes)
        assert len(set(n['id'] for n in notes)) == len(notes)
        assert notes[0]['key'] is None and notes[-1]['key'] is None
        assert record['breathAfter'][-1] == [index, len(moras)]
        rests = [n for n in notes[1:] if n['key'] is None]
        assert len(rests) == len(record['breathAfter'])
        for nindex, note in enumerate(notes[1:], 1):
            if note['key'] is None:
                assert note['frame_length'] == 28
                assert notes[nindex - 1]['id'] in {f'{s}:{m}' for s, m in record['breathAfter']}
            elif note['lyric'] == 'ッ':
                assert note['frame_length'] == 18 and notes[nindex - 1]['frame_length'] >= 42
        query = record['query']
        frames = sum(n['frame_length'] for n in notes)
        assert len(query['f0']) == len(query['volume']) == sum(p['frame_length'] for p in query['phonemes']) == frames
        assert query['outputSamplingRate'] == 24000 and not query['outputStereo']
        assert all(math.isfinite(x) and 0 <= x <= 197 for x in query['f0'])
        positive = [x for x in query['f0'] if x > 0]
        assert 195 <= statistics.median(positive) <= 197
        phones = defaultdict(list)
        for phone in query['phonemes']:
            assert phone['frame_length'] >= 0
            phones[phone['note_id']].append(phone['phoneme'])
            if phone['phoneme'] == 'cl':
                assert 5 <= phone['frame_length'] <= 15, (record['file'], phone)
        assert set(phones) == {n['id'] for n in notes}
        for mindex, mora in enumerate(moras, 1):
            expected = ([mora['consonant']] if mora['consonant'] else []) + [mora['vowel'] if mora['vowel'] == 'N' else mora['vowel'].lower()]
            assert phones[f'{index}:{mindex}'] == expected, (record['file'], mora, phones[f'{index}:{mindex}'])
        vowel_lengths = [p['frame_length'] / 93.75 for p in query['phonemes'] if p['phoneme'] in ('a', 'i', 'u', 'e', 'o', 'N')]
        assert statistics.median(vowel_lengths) > .2
        assert query['phonemes'][0]['phoneme'] == 'pau'
        trim = record['trimLeadingFrames']
        assert 0 <= trim == max(0, query['phonemes'][0]['frame_length'] - 2)
        path = audio_dir / record['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], path
        with wave.open(str(path)) as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
            seconds = wav.getnframes() / 24000
            assert abs(seconds - record['seconds']) < .001 and .5 < seconds < 20
            assert wav.getnframes() == (frames - trim) * 256
            samples = array.array('h', wav.readframes(wav.getnframes()))
        assert 100 < max(abs(v) for v in samples) <= 30001
        rms = math.sqrt(sum(v*v for v in samples) / len(samples))
        assert abs(20 * math.log10(rms / manifest['design']['targetRms'])) < .5
        total += seconds
    print(f"Verified {len(manifest['files'])} WhiteCUL WAVs: {total:.1f}s; exact pronunciation/phonemes, sustained vowels, hashes and no clipping")


if __name__ == '__main__':
    check()
