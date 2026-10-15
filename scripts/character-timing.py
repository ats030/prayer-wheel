"""Derive character cues from explicit readings and the shipped synthesis phonemes."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def canonical(text):
    text = ''.join(chr(ord(c) - 96) if 'ァ' <= c <= 'ヶ' else c for c in text)
    return re.sub(r'([こごそぞとどのほぼぽもよろょ])う', r'\1お', text)


def build(sutra_path=None, manifest_path=None, mapping=None):
    raw = (sutra_path or ROOT / 'data/sutra.json').read_bytes()
    sutra = json.loads(raw)
    manifest = json.loads((manifest_path or ROOT / 'audio/manifest.json').read_text(encoding='utf-8'))
    if mapping is None:
        mapping = json.loads((ROOT / 'data/character-readings.json').read_text(encoding='utf-8'))['sections']
    assert manifest['sutraSha256'] == hashlib.sha256(raw).hexdigest()
    assert len(mapping) == len(sutra['chunks']) == len(manifest['files'])
    sections = []
    for index, (chunk, record, group) in enumerate(zip(sutra['chunks'], manifest['files'], mapping), 1):
        assert group['text'] == chunk['text'].replace('　', '')
        assert len(group['text']) == len(group['readings'])
        assert ''.join(group['readings']) == re.sub('[、。　 ]', '', chunk['reading'])
        assert hashlib.sha256((ROOT / 'audio' / record['file']).read_bytes()).hexdigest() == record['sha256']
        moras = [m['text'] for p in record['sourceQuery']['accent_phrases'] for m in p['moras']]
        intervals = {}
        frame = -record['trimLeadingFrames']
        for phone in record['query']['phonemes']:
            start = frame * 256 / 24000
            frame += phone['frame_length']
            end = frame * 256 / 24000
            if phone['note_id'] not in intervals:
                intervals[phone['note_id']] = [start, end]
            else:
                intervals[phone['note_id']][1] = end
        assert abs(frame * 256 / 24000 - record['seconds']) < 1e-9
        characters = []
        cursor = 0
        for char, reading in zip(group['text'], group['readings']):
            count = sum(c not in 'ゃゅょぁぃぅぇぉゎ' for c in reading)
            assert count > 0 and cursor + count <= len(moras)
            actual = ''.join(moras[cursor:cursor + count])
            assert canonical(actual) == canonical(reading), (index, char, reading, actual)
            start = intervals[f'{index}:{cursor + 1}'][0]
            end = intervals[f'{index}:{cursor + count}'][1]
            assert 0 <= start < end <= record['seconds']
            assert not characters or characters[-1]['end'] <= start
            characters.append({'text': char, 'reading': reading, 'start': start, 'end': end})
            cursor += count
        assert cursor == len(moras)
        assert characters[-1]['end'] < record['seconds'], 'A section spacer needs the existing final rest'
        sections.append({'audioSha256': record['sha256'],
                         'file': f"synced/{record['sha256']}/{index:02d}.wav",
                         'duration': record['seconds'], 'characters': characters})
    return {'version': 1, 'sutraSha256': manifest['sutraSha256'], 'sections': sections}


if __name__ == '__main__':
    result = build()
    print(f"Verified {sum(len(s['characters']) for s in result['sections'])} character cues from 29 WAV synthesis traces")
