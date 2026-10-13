#!/usr/bin/env python3
"""Build an isolated five-section A/B listening sample; never rewrite shipped audio."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import statistics
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('generator', ROOT / 'scripts/generate-audio.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
SETTINGS = {**generator.SETTINGS, 'intonationScale': 0.2,
            'prePhonemeLength': 0.03, 'postPhonemeLength': 0.08}



def frames(data):
    with wave.open(io.BytesIO(data)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) == (1, 2, 24000)
        return reader.readframes(reader.getnframes())


def save_wave(path, parts):
    with wave.open(str(path), 'wb') as writer:
        writer.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        for part in parts:
            writer.writeframes(part)
    data = path.read_bytes()
    return {'file': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
            'seconds': round(len(frames(data)) / 48000, 4)}


def generate(host):
    engine = json.loads(generator.request(host, '/engine_manifest'))
    assert engine['uuid'] == '208cf94d-43d2-4cf5-abc0-9783cac36d29'
    assert json.loads(generator.request(host, '/version')) == generator.ENGINE_VERSION
    voice = next(v for v in json.loads(generator.request(host, '/speakers'))
                 if v['speaker_uuid'] == generator.SPEAKER_UUID)
    assert any(s['id'] == generator.SPEAKER_ID for s in voice['styles'])
    raw = (ROOT / 'data/sutra.json').read_bytes()
    chunks = json.loads(raw)['chunks'][1:6]
    output = ROOT / 'audition'
    output.mkdir(exist_ok=True)
    current, adjusted, sections = [], [], []
    for index, (chunk, reading) in enumerate(((chunk, chunk["reading"]) for chunk in chunks), 2):
        params = generator.urllib.parse.urlencode({'speaker': generator.SPEAKER_ID, 'text': reading})
        query = json.loads(generator.request(host, '/audio_query?' + params, b''))
        query.update(SETTINGS)
        moras = [m for phrase in query['accent_phrases'] for m in phrase['moras']]
        pitches = [m['pitch'] for m in moras if m['pitch'] > 0]
        center = statistics.median(pitches)
        # Keep consonants and unvoiced vowels; regularize voiced vowel duration/pitch.
        for mora in moras:
            if mora['pitch'] > 0:
                mora['vowel_length'] = max(0.07, min(0.18, 0.12 + (mora['vowel_length'] - 0.12) * 0.25))
                mora['pitch'] = center + (mora['pitch'] - center) * 0.2
        for phrase in query['accent_phrases']:
            if phrase.get('pause_mora'):
                phrase['pause_mora']['vowel_length'] = 0.04
        data = generator.request(host, f'/synthesis?speaker={generator.SPEAKER_ID}&enable_interrogative_upspeak=false',
                                 json.dumps(query).encode())
        original = (ROOT / 'audition/baseline' / f'{index:02d}.wav').read_bytes()
        current.append(frames(original))
        adjusted.append(frames(data))
        sections.append({'section': index, 'text': chunk['text'], 'reading': reading,
                         'currentSha256': hashlib.sha256(original).hexdigest(),
                         'adjustedSha256': hashlib.sha256(data).hexdigest(), 'query': query})
        print(f'Generated section {index}: {query["kana"]}', flush=True)
    files = [save_wave(output / 'current.wav', current), save_wave(output / 'adjusted.wav', adjusted)]
    metadata = {'engineVersion': generator.ENGINE_VERSION, 'speakerId': generator.SPEAKER_ID,
                'speakerUuid': generator.SPEAKER_UUID, 'voiceVersion': voice['version'],
                'credit': 'VOICEVOX Nemo', 'settings': SETTINGS, 'sutraSha256': hashlib.sha256(raw).hexdigest(),
                'pitchRetention': 0.2, 'vowelLengthRetention': 0.25, 'pauseSeconds': 0.04,
                'sections': sections, 'files': files}
    (output / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(files)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='http://127.0.0.1:50121')
    generate(parser.parse_args().engine.rstrip('/'))
