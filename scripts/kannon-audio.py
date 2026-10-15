#!/usr/bin/env python3
"""Generate or verify Kannon verse audio with explicit kana and the existing voice."""
import argparse
import array
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import urllib.parse
import wave

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


chant = module('chant', 'generate-chant.py')
timing = module('timing', 'character-timing.py')


def check():
    source = json.loads((ROOT / 'data/kannon.json').read_text())
    manifest = json.loads((ROOT / 'audio/kannon-manifest.json').read_text())
    assert len(source['chunks']) == len(manifest['files']) == 52
    assert sum(len(c['text'].replace('　', '')) for c in source['chunks']) == 520
    assert manifest['speakerId'] == 3023 and manifest['teacherId'] == 6000
    for chunk, record in zip(source['chunks'], manifest['files']):
        assert chunk['text'] == record['text'] and chunk['reading'] == record['reading']
        assert chunk['translation'].strip()
        assert ''.join(chunk['characterReadings']) == chunk['reading'].replace('、', '').replace('。', '')
        samples = chant.read_pcm((ROOT / 'audio' / record['file']).read_bytes())
        assert len(samples) / 24000 == record['seconds']
        assert 0 < max(abs(v) for v in samples) <= 30000
    mapping = [{'text': c['text'].replace('　', ''), 'readings': c['characterReadings']} for c in source['chunks']]
    cues = timing.build(ROOT / 'data/kannon.json', ROOT / 'audio/kannon-manifest.json', mapping)
    print(f"Kannon: {len(cues['sections'])} WAVs, 520 character cues and source/audio hashes PASS")
    return cues


def generate(host):
    config = chant.VARIANTS['whitecul']
    engine, voice, teacher = chant.verify_engine(host, config)
    raw = (ROOT / 'data/kannon.json').read_bytes()
    source = json.loads(raw)
    target = chant.rms(chant.read_pcm((ROOT / 'audition/current.wav').read_bytes()))
    records = []
    with tempfile.TemporaryDirectory(prefix='prayer-kannon-') as tmp:
        work = Path(tmp)
        for number, chunk in enumerate(source['chunks'], 1):
            # The kana parser preserves traditional readings, avoiding TTS guesses.
            kana = ''.join(timing.canonical(reading) for reading in chunk['characterReadings'])
            kana = ''.join(chr(ord(c) + 96) if 'ぁ' <= c <= 'ゖ' else c for c in kana) + "'"
            params = urllib.parse.urlencode({'speaker': 23, 'text': kana, 'is_kana': 'true'})
            phrases = json.loads(chant.audio_generator.request(host, '/accent_phrases?' + params, b''))
            query_source = {'accent_phrases': phrases, 'kana': kana}
            actual = ''.join(m['text'] for p in phrases for m in p['moras'])
            assert timing.canonical(actual) == timing.canonical(''.join(chunk['characterReadings']))
            count = sum(len(p['moras']) for p in phrases)
            score, _ = chant.build_score({'sections': [{'section': number, **chunk, 'query': query_source}]}, 50, {(number, count)})
            ending_ids = set()
            for i, note in enumerate(score['notes'][1:], 1):
                if note['key'] is None:
                    note['frame_length'] = 8
                    score['notes'][i - 1]['frame_length'] = 30
                    ending_ids.add(score['notes'][i - 1]['id'])
            query = json.loads(chant.request(host, '/sing_frame_audio_query?speaker=6000', score))
            chant.shape_pitch(query, score, ending_ids)
            phones = [p['phoneme'] for p in query['phonemes'] for _ in range(p['frame_length'])]
            voiced = [v for v, p in zip(query['volume'], phones) if p in {'a', 'i', 'u', 'e', 'o', 'N'} and v > 0]
            level = statistics.median(voiced)
            query['volume'] = [(v + level) / 2 if p in {'a', 'i', 'u', 'e', 'o', 'N'} and v > level else v for v, p in zip(query['volume'], phones)]
            assert query['phonemes'][0]['phoneme'] == 'pau'
            trim = max(0, query['phonemes'][0]['frame_length'] - 2)
            samples = chant.read_pcm(chant.request(host, '/frame_synthesis?speaker=3023', query))[trim * 256:]
            gain = min(target / chant.rms(samples), 30000 / max(abs(v) for v in samples))
            normalized = array.array('h', (round(v * gain) for v in samples))
            if sys.byteorder != 'little':
                normalized.byteswap()
            name = f'{number:02d}.wav'
            with wave.open(str(work / name), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(normalized.tobytes())
            records.append({'file': 'kannon/' + name, 'text': chunk['text'], 'reading': chunk['reading'],
                            'sourceQuery': query_source, 'query': query, 'score': score,
                            'trimLeadingFrames': trim, 'gain': gain,
                            'seconds': len(samples) / 24000,
                            'sha256': hashlib.sha256((work / name).read_bytes()).hexdigest()})
            print(f'{number}/52 {chunk["text"]} {records[-1]["seconds"]:.2f}s', flush=True)
        manifest = {'engineVersion': '0.25.2', 'voiceVersion': voice['version'], 'speakerId': 3023,
                    'teacherId': 6000, 'teacherVersion': teacher['version'],
                    'credit': 'VOICEVOX:WhiteCUL / VOICEVOX:波音リツ（歌唱クエリ生成）',
                    'pronunciation': 'VOICEVOX explicit kana parser; no automatic kanji reading',
                    'sutraSha256': hashlib.sha256(raw).hexdigest(), 'files': records}
        (ROOT / 'audio/kannon').mkdir(exist_ok=True)
        for record in records:
            shutil.copyfile(work / Path(record['file']).name, ROOT / 'audio' / record['file'])
        (ROOT / 'audio/kannon-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    check()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate', action='store_true')
    parser.add_argument('--engine', default='http://127.0.0.1:50021')
    args = parser.parse_args()
    generate(args.engine.rstrip('/')) if args.generate else check()
