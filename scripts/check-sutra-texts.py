#!/usr/bin/env python3
"""Guard the complete classical bodies checked against the recorded witnesses."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Independent whole-body comparison, not hashes of the generated WAV metadata.
# Witness URLs, character normalization and editorial boundaries are documented
# in docs/sutra-selection.md. Recheck witnesses before updating these digests.
WITNESSES = {
    'hachidai': (45, 372, 'c2e247f0b05d6e04319199c04d900f5c8e23eb9debc1ffc9647c6ad202e539cf'),
    'amida': (112, 1857, '90af9411b9fabfb74549211c0f2b60eb6bdc8f2368c405b8840ac6514802fc9e'),
}


def check():
    for sutra_id, (sections, characters, digest) in WITNESSES.items():
        source = json.loads((ROOT / f'data/{sutra_id}.json').read_text())
        body = ''.join(chunk['text'] for chunk in source['chunks'])
        assert len(source['chunks']) == sections and len(body) == characters
        assert hashlib.sha256(body.encode()).hexdigest() == digest, f'{sutra_id}: recheck the complete witness'
        for chunk in source['chunks']:
            assert len(chunk['text']) == len(chunk['characterReadings'])
            assert chunk['reading'] == ''.join(chunk['characterReadings']) + '。'
            assert chunk['translation'].strip()
        if sutra_id == 'amida':
            assert body.count('如是等恒河沙数諸仏各於其国') == 6
            assert body.endswith('聞仏所説歓喜信受作礼而去')
        else:
            assert all(body.count(f'第{n}覚') == 1 for n in '一二三四五六七八')
            assert body.endswith('永断生死常住快楽')
        print(f"{source['title']}: complete {characters}-character body and {sections} explicit reading/meaning sections PASS")


if __name__ == '__main__':
    check()
