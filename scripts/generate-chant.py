#!/usr/bin/env python3
"""Create a separate sustained-vowel chant sample using VOICEVOX humming."""
import argparse
import array
import hashlib
import importlib.util
import io
import json
import math
import sys
from pathlib import Path
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audio_generator', ROOT / 'scripts/generate-audio.py')
audio_generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio_generator)
ENGINE_VERSION = '0.25.2'
ENGINE_UUID = '074fc39e-678b-4c13-8916-ffca8d505d1d'
VARIANTS = {
    'sorin': {'label': 'C', 'uuid': '7d1e7ba7-f957-40e5-a3fc-da49f769ab65',
              'id': 3053, 'midi': 46, 'file': 'chant.wav', 'manifest': 'chant-manifest.json'},
    'whitecul': {'label': 'D', 'uuid': '67d5d8da-acd7-4207-bb10-b5542d3a663b',
                 'id': 3023, 'midi': 55, 'file': 'chant-female.wav', 'manifest': 'chant-female-manifest.json'},
}
TEACHER_UUID = 'b1a81618-b27b-40d2-b0ea-27a9ad408c4b'
TEACHER_ID = 6000
MORA_FRAMES, END_FRAMES, REST_FRAMES, CLOSURE_FRAMES = 30, 45, 28, 18
BREATH_AFTER = {(3, 13), (4, 11), (4, 19), (5, 15), (6, 14)}


def request(host, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    return audio_generator.request(host, path, body)


def read_pcm(data):
    with wave.open(io.BytesIO(data)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
            raise ValueError('Expected mono 24kHz PCM16 WAV')
        samples = array.array('h', wav.readframes(wav.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def rms(samples):
    return math.sqrt(sum(v * v for v in samples) / len(samples))


def build_score(manifest, midi_key, breath_after=None):
    if breath_after is None:
        breath_after = BREATH_AFTER
    notes = [{'id': 'leading-rest', 'key': None, 'frame_length': 15, 'lyric': ''}]
    sections = []
    for section in manifest['sections']:
        number = section['section']
        moras = [m['text'] for p in section['query']['accent_phrases'] for m in p['moras']]
        sections.append({'section': number, 'text': section['text'], 'reading': section['reading'], 'moras': moras})
        for index, mora in enumerate(moras, 1):
            ending = (number, index) in breath_after
            length = END_FRAMES if ending else MORA_FRAMES
            if mora == 'ッ':
                # Keep the consonant closure short; sustain the preceding vowel instead.
                notes[-1]['frame_length'] += MORA_FRAMES - CLOSURE_FRAMES
                length = CLOSURE_FRAMES
            notes.append({'id': f'{number}:{index}', 'key': midi_key,
                          'frame_length': length, 'lyric': mora})
            if ending:
                notes.append({'id': f'breath-{number}:{index}', 'key': None,
                              'frame_length': REST_FRAMES, 'lyric': ''})
    return {'notes': notes}, sections


def shape_pitch(query, score):
    # No added vibrato. Hold each breath group near one note, with a small end fall.
    total = sum(n['frame_length'] for n in score['notes'])
    if len(query['f0']) != total or len(query['volume']) != total:
        raise ValueError('Unexpected frame query length')
    midi_key = next(n['key'] for n in score['notes'] if n['key'] is not None)
    base_hz = 440 * 2 ** ((midi_key - 69) / 12)
    start = 0
    for note in score['notes']:
        length = note['frame_length']
        for offset in range(length):
            frame = start + offset
            if query['f0'][frame] > 0:
                progress = offset / max(length - 1, 1)
                fall = -0.8 * progress if length == END_FRAMES else 0
                query['f0'][frame] = base_hz * 2 ** (fall / 12)
        start += length
    query['outputSamplingRate'], query['outputStereo'] = 24000, False
    query['volumeScale'] = 1.0


def verify_engine(host, config):
    engine = json.loads(request(host, '/engine_manifest'))
    if engine['uuid'] != ENGINE_UUID or json.loads(request(host, '/version')) != ENGINE_VERSION:
        raise ValueError('Expected official VOICEVOX Engine 0.25.2')
    if not engine['supported_features']['sing']:
        raise ValueError('Singing feature unavailable')
    singers = json.loads(request(host, '/singers'))
    voice = next(v for v in singers if v['speaker_uuid'] == config['uuid'])
    teacher = next(v for v in singers if v['speaker_uuid'] == TEACHER_UUID)
    if voice['version'] != '0.16.0' or teacher['version'] != '0.16.0':
        raise ValueError('Expected voice libraries 0.16.0')
    if not any(s['id'] == config['id'] and s['type'] == 'frame_decode' for s in voice['styles']):
        raise ValueError('Wrong humming voice')
    if not any(s['id'] == TEACHER_ID and s['type'] == 'sing' for s in teacher['styles']):
        raise ValueError('Wrong singing teacher')
    if not math.isclose(engine['frame_rate'], 93.75):
        raise ValueError('Unexpected singing frame rate')
    return engine, voice, teacher


def generate(host, variant):
    config = VARIANTS[variant]
    engine, voice, teacher = verify_engine(host, config)
    previous_raw = (ROOT / 'audition/manifest.json').read_bytes()
    previous = json.loads(previous_raw)
    score, sections = build_score(previous, config["midi"])
    query = json.loads(request(host, f'/sing_frame_audio_query?speaker={TEACHER_ID}', score))
    shape_pitch(query, score)
    raw = request(host, f"/frame_synthesis?speaker={config['id']}", query)
    samples = read_pcm(raw)
    reference = read_pcm((ROOT / 'audition/current.wav').read_bytes())
    gain = min(rms(reference) / rms(samples), 30000 / max(abs(v) for v in samples))
    normalized = array.array('h', (round(v * gain) for v in samples))
    if sys.byteorder != 'little':
        normalized.byteswap()
    out = ROOT / 'audition' / config['file']
    with wave.open(str(out), 'wb') as wav:
        wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        wav.writeframes(normalized.tobytes())
    metadata = {'engineVersion': ENGINE_VERSION, 'engineUuid': ENGINE_UUID,
                'voice': voice['name'], 'voiceVersion': voice['version'],
                'speakerUuid': config['uuid'], 'speakerId': config['id'],
                'teacher': teacher['name'], 'teacherVersion': teacher['version'],
                'teacherUuid': TEACHER_UUID, 'teacherId': TEACHER_ID,
                'credit': f"VOICEVOX:{voice['name']} / VOICEVOX:波音リツ（歌唱クエリ生成）",
                'priorManifestSha256': hashlib.sha256(previous_raw).hexdigest(),
                'sutraSha256': previous['sutraSha256'], 'frameRate': engine['frame_rate'],
                'design': {'midiKey': config['midi'], 'moraFrames': MORA_FRAMES, 'endingFrames': END_FRAMES,
                           'breathFrames': REST_FRAMES, 'closureFrames': CLOSURE_FRAMES,
                           'breathAfter': [list(point) for point in sorted(BREATH_AFTER)], 'endFallSemitones': 0.8,
                           'effects': [], 'gain': gain, 'targetRms': rms(reference)},
                'sections': sections, 'score': score, 'query': query,
                'file': {'file': out.name, 'seconds': len(samples) / 24000,
                         'sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
                         'rawSynthesisSha256': hashlib.sha256(raw).hexdigest()}}
    (ROOT / 'audition' / config['manifest']).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    print(f"Generated {config['label']}: {voice['name']}, {len(samples) / 24000:.2f}s, {len(score['notes'])} notes/rests; gain {gain:.3f}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='http://127.0.0.1:50021')
    parser.add_argument('--voice', choices=['all', *VARIANTS], default='all')
    args = parser.parse_args()
    for variant in VARIANTS if args.voice == 'all' else (args.voice,):
        generate(args.engine.rstrip('/'), variant)
