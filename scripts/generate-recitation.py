#!/usr/bin/env python3
"""Generate all main sections with the selected WhiteCUL D voice, retaining auditions."""
import argparse
import array
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.parse
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('chant', ROOT / 'scripts/generate-chant.py')
chant = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chant)


def breath_points(reading, section, moras):
    # The selected D sample supplies its explicit internal breathing points.
    # Every separately playable section also gets a complete final release.
    points = {point for point in chant.BREATH_AFTER if point[0] == section}
    if not 2 <= section <= 6:
        count = 0
        for char in reading:
            if char not in '、。　 ゃゅょぁぃぅぇぉゎ':
                count += 1
            if char == '。' and count:
                points.add((section, count))
        if count != len(moras):
            raise ValueError(f'Mora count mismatch in section {section}')
    points.add((section, len(moras)))
    return points


def generate(host, nemo):
    config = chant.VARIANTS['whitecul']
    engine, voice, teacher = chant.verify_engine(host, config)
    baseline_raw = (ROOT / 'audition/baseline/manifest.json').read_bytes()
    baseline = json.loads(baseline_raw)
    nemo_manifest = json.loads(chant.audio_generator.request(nemo, '/engine_manifest'))
    nemo_version = json.loads(chant.audio_generator.request(nemo, '/version'))
    if nemo_manifest['uuid'] != '208cf94d-43d2-4cf5-abc0-9783cac36d29' or nemo_version != '0.24.0':
        raise ValueError('Pronunciation source must be official Nemo 0.24.0')
    raw_sutra = (ROOT / 'data/sutra.json').read_bytes()
    if hashlib.sha256(raw_sutra).hexdigest() != baseline['sutraSha256']:
        raise ValueError('Pronunciation baseline no longer matches sutra')
    sutra = json.loads(raw_sutra)
    reference = chant.read_pcm((ROOT / 'audition/current.wav').read_bytes())
    target_rms = chant.rms(reference)
    records = []
    # Finish every synthesis and integrity check before replacing shipped files.
    with tempfile.TemporaryDirectory(prefix='prayer-wheel-recitation-') as work:
        output = Path(work)
        for index, chunk in enumerate(sutra['chunks'], 1):
            params = urllib.parse.urlencode({'speaker': 10001, 'text': chunk['reading']})
            source = json.loads(chant.audio_generator.request(nemo, '/audio_query?' + params, b''))
            if source['kana'] != baseline['files'][index - 1]['kana']:
                raise ValueError(f'Pronunciation drift in section {index}')
            moras = [m for phrase in source['accent_phrases'] for m in phrase['moras']]
            points = breath_points(chunk['reading'], index, moras)
            score, sections = chant.build_score({'sections': [{'section': index, **chunk, 'query': source}]},
                                                config['midi'], points)
            query = json.loads(chant.request(host, f'/sing_frame_audio_query?speaker={chant.TEACHER_ID}', score))
            chant.shape_pitch(query, score)
            if query['phonemes'][0]['phoneme'] != 'pau':
                raise ValueError('Cannot safely trim leading silence')
            trim_frames = max(0, query['phonemes'][0]['frame_length'] - 2)
            data = chant.request(host, f"/frame_synthesis?speaker={config['id']}", query)
            samples = chant.read_pcm(data)[trim_frames * 256:]
            gain = min(target_rms / chant.rms(samples), 30000 / max(abs(v) for v in samples))
            normalized = array.array('h', (round(v * gain) for v in samples))
            if sys.byteorder != 'little':
                normalized.byteswap()
            name = f'{index:02d}.wav'
            with wave.open(str(output / name), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(normalized.tobytes())
            record = {'file': name, 'section': index, 'text': chunk['text'], 'reading': chunk['reading'],
                      'kana': source['kana'], 'seconds': len(samples) / 24000,
                      'sha256': hashlib.sha256((output / name).read_bytes()).hexdigest(),
                      'sourceQuery': source, 'score': score, 'query': query,
                      'breathAfter': [list(point) for point in sorted(points)],
                      'trimLeadingFrames': trim_frames, 'gain': gain}
            records.append(record)
            print(f'{name}: {record["seconds"]:.2f}s / {source["kana"]}', flush=True)
        metadata = {'engine': engine['name'], 'engineVersion': chant.ENGINE_VERSION,
                    'engineUuid': chant.ENGINE_UUID, 'voice': voice['name'], 'voiceVersion': voice['version'],
                    'speakerId': config['id'], 'speakerUuid': config['uuid'],
                    'teacher': teacher['name'], 'teacherId': chant.TEACHER_ID,
                    'teacherUuid': chant.TEACHER_UUID, 'teacherVersion': teacher['version'],
                    'credit': 'VOICEVOX:WhiteCUL / VOICEVOX:波音リツ（歌唱クエリ生成）',
                    'frameRate': engine['frame_rate'], 'sutraSha256': hashlib.sha256(raw_sutra).hexdigest(),
                    'baselineManifestSha256': hashlib.sha256(baseline_raw).hexdigest(),
                    'design': {'midiKey': 55, 'moraFrames': 30, 'endingFrames': 45, 'closureFrames': 18,
                               'breathFrames': 28, 'endFallSemitones': .8, 'effects': [], 'targetRms': target_rms},
                    'files': records}
        (output / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        validator_spec = importlib.util.spec_from_file_location('validation', ROOT / 'scripts/check-audio.py')
        validator = importlib.util.module_from_spec(validator_spec)
        validator_spec.loader.exec_module(validator)
        validator.check(output)
        for record in records:
            shutil.copyfile(output / record['file'], ROOT / 'audio' / record['file'])
        shutil.copyfile(output / 'manifest.json', ROOT / 'audio/manifest.json')
        print(f'Installed {len(records)} validated WhiteCUL sections; audition files unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', default='http://127.0.0.1:50021')
    parser.add_argument('--pronunciation-engine', default='http://127.0.0.1:50121')
    args = parser.parse_args()
    generate(args.engine.rstrip('/'), args.pronunciation_engine.rstrip('/'))
