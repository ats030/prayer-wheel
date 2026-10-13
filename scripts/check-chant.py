#!/usr/bin/env python3
"""Validate sustained chant provenance, mora sequence, frame alignment, low F0 and signal."""
import array
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import wave

ROOT = Path(__file__).resolve().parents[1]

def check(label, manifest_name, file_name, speaker_id, speaker_uuid, midi_key):
    m = json.loads((ROOT / 'audition' / manifest_name).read_text())
    previous_raw = (ROOT / 'audition/manifest.json').read_bytes()
    previous = json.loads(previous_raw)
    assert m['priorManifestSha256'] == hashlib.sha256(previous_raw).hexdigest()
    assert m['sutraSha256'] == hashlib.sha256((ROOT / 'audition/baseline/sutra.json').read_bytes()).hexdigest()
    assert m['engineVersion'] == '0.25.2' and m['engineUuid'] == '074fc39e-678b-4c13-8916-ffca8d505d1d'
    assert m['speakerId'] == speaker_id and m['speakerUuid'] == speaker_uuid
    assert m['teacherId'] == 6000 and m['teacherUuid'] == 'b1a81618-b27b-40d2-b0ea-27a9ad408c4b'
    assert m['design']['effects'] == []
    assert m['voiceVersion'] == m['teacherVersion'] == '0.16.0'
    assert m['design']['midiKey'] == midi_key
    assert m['design']['breathAfter'] == [[3, 13], [4, 11], [4, 19], [5, 15], [6, 14]]
    assert [s['section'] for s in m['sections']] == [2, 3, 4, 5, 6]
    for section, source in zip(m['sections'], previous['sections']):
        assert section['text'] == source['text'] and section['reading'] == source['reading']
        assert section['moras'] == [mora['text'] for p in source['query']['accent_phrases'] for mora in p['moras']]
    notes = m['score']['notes']
    assert len({n['id'] for n in notes}) == len(notes)
    assert [n['lyric'] for n in notes if n['key'] is not None] == [mora for s in m['sections'] for mora in s['moras']]
    assert notes[0]['key'] is None and notes[-1]['key'] is None
    for index, note in enumerate(notes[1:], 1):
        if note['key'] is None:
            assert notes[index - 1]['id'] in {f'{s}:{i}' for s, i in m['design']['breathAfter']}
    assert len([n for n in notes if n['key'] is None]) == 6
    assert all(n['key'] == midi_key for n in notes if n['key'] is not None)
    assert all(n['frame_length'] in (18, 30, 42, 45) for n in notes if n['key'] is not None)
    for index, note in enumerate(notes):
        if note['lyric'] == 'ッ':
            assert note['frame_length'] == 18 and notes[index - 1]['frame_length'] == 42

    q = m['query']
    frames = sum(n['frame_length'] for n in notes)
    assert len(q['f0']) == len(q['volume']) == sum(p['frame_length'] for p in q['phonemes']) == frames
    assert {p['note_id'] for p in q['phonemes']} == {n['id'] for n in notes}
    phonemes_by_note = defaultdict(list)
    for phoneme in q['phonemes']:
        phonemes_by_note[phoneme['note_id']].append(phoneme['phoneme'])
    for source in previous['sections']:
        moras = [mora for phrase in source['query']['accent_phrases'] for mora in phrase['moras']]
        for index, mora in enumerate(moras, 1):
            vowel = mora['vowel'] if mora['vowel'] == 'N' else mora['vowel'].lower()
            expected = ([mora['consonant']] if mora['consonant'] else []) + [vowel]
            assert phonemes_by_note[f"{source['section']}:{index}"] == expected, 'Rendered phoneme sequence changed'
    assert all(5 <= p['frame_length'] <= 15 for p in q['phonemes'] if p['phoneme'] == 'cl'), 'Consonant closure outside 5–15 frames'
    assert q['outputSamplingRate'] == 24000 and not q['outputStereo']
    base_hz = 440 * 2 ** ((midi_key - 69) / 12)
    assert all(math.isfinite(x) and 0 <= x < base_hz * 1.01 for x in q['f0'])
    f0 = [x for x in q['f0'] if x > 0]
    assert abs(statistics.median(f0) - base_hz) < 1 and len(f0) > frames * .4
    vowels = [p['frame_length'] / m['frameRate'] for p in q['phonemes'] if p['phoneme'] in ('a', 'i', 'u', 'e', 'o', 'N')]
    assert statistics.median(vowels) > .2, 'Vowels no longer sustained'
    record = m['file']
    assert record['file'] == file_name
    path = ROOT / 'audition' / file_name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
    with wave.open(str(path)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        seconds = wav.getnframes() / 24000
        assert abs(seconds - record['seconds']) < .001 and abs(seconds - frames / m['frameRate']) < .001
        samples = array.array('h', wav.readframes(wav.getnframes()))
    assert 100 < max(abs(v) for v in samples) <= 30001
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    assert abs(20 * math.log10(rms / m['design']['targetRms'])) < .5, 'Comparison level changed'
    print(f'Verified {label}: {seconds:.2f}s; exact 69-mora sequence, sustained vowels, {base_hz:.1f}Hz F0, PCM, hashes and level')

check('C', 'chant-manifest.json', 'chant.wav', 3053, '7d1e7ba7-f957-40e5-a3fc-da49f769ab65', 46)
check('D', 'chant-female-manifest.json', 'chant-female.wav', 3023, '67d5d8da-acd7-4207-bb10-b5542d3a663b', 55)
