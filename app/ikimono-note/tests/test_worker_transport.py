import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import prepared_photos
import vision


def test_native_transport_boundary_and_byte_parity():
    node = shutil.which('node')
    assert node, 'Node is required for native transport validation'
    def jpeg(size=(600, 450), **kwargs):
        out = io.BytesIO()
        Image.new('RGB', size, 'green').save(out, 'JPEG', **kwargs)
        return out.getvalue()
    good = jpeg()
    assert prepared_photos.jpeg_dimensions(good) == (600, 450)
    bad = [jpeg(exif=b'Exif\x00\x00private'), jpeg((1601, 450)), good[:-2], b'not-jpeg',
           good + b'x' * (prepared_photos.MAX_PREPARED_BYTES + 1)]
    cases = {'template': vision.provider_payload('gemini', 'gemini-test', [], location='山麓', observed_date='2026-10-09'),
             'good': base64.b64encode(good).decode(),
             'large': base64.b64encode(good[:-2] + bytes(prepared_photos.MAX_PREPARED_BYTES - len(good)) + good[-2:]).decode(),
             'badPhotos': [base64.b64encode(raw).decode() for raw in bad]}
    result = subprocess.run([node, 'tests/check_worker_transport.mjs'], cwd=APP,
        input=json.dumps(cases), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'PASS:' in result.stdout
    assert 'legacy/new acceptance comparisons' in result.stdout
