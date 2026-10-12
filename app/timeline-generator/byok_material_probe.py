"""Fixed Showa retrieval probe; fake model transport, no real provider/key."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error('Output already exists; no overwrite')
os.environ['TIMELINE_SOURCE'] = 'wikipedia'
os.environ['TIMELINE_SOURCE_FILTER'] = ''
os.environ['TIMELINE_FOOTNOTE_FILTER'] = ''
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import timeline
from byok import ModelSession
from byok_metrics import MaterialMetrics
from byok_pipeline import FetchBudget

hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
          for name in ('timeline.py', 'byok.py', 'byok_metrics.py', 'byok_pipeline.py')}
started = time.monotonic()
budget = FetchBudget(100, 40_000_000)
timeline.json_request = budget.json
original = timeline.WebReader.request
timeline.WebReader.request = lambda reader, url, limit=2_000_000: budget.article(original, reader, url, limit)
metrics = MaterialMetrics(timeline)
query = timeline.parse_query('昭和')
results = timeline.search(query)  # No deadline: no model-assisted query.
sources = timeline.fetch_sources(timeline.WebReader(time.monotonic() + 60), results)
batches = list(timeline.material_batches(sources, query))
payload_sizes = []

def fake_send(key, payload, timeout):
    payload_sizes.append(len(payload))
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"theme": "昭和", "events": []}'}]}}],
            'usageMetadata': {'promptTokenCount': 0, 'candidatesTokenCount': 0, 'totalTokenCount': 0}}

# Fake key and transport only. No Google connection, tokens or usage measurement.
model = ModelSession('AIza' + 'x' * 35, threading.Event(), max_cost_microusd=5_000_000,
                     max_calls=100, input_bytes=100_000, output_tokens=6000,
                     min_call_interval=0, send=fake_send)
try:
    for batch in batches:
        timeline.generate_batch(query, batch, time.monotonic() + 10, model=model)
finally:
    model.close()
report = {'theme': '昭和', 'probe': 'retrieval_and_local_serialization_only',
          'conditions': {'source': 'wikipedia', 'source_filter': '', 'footnote_filter': '',
                         'model_assisted_search': False, 'sha256': hashes},
          'material': metrics.summary(), 'fetch': {'calls': budget.calls, 'bytes': budget.bytes},
          'planned_generate_payloads': len(payload_sizes),
          'planned_generate_payload_bytes': sum(payload_sizes),
          'max_generate_payload_bytes': max(payload_sizes, default=0),
          'elapsed_seconds': round(time.monotonic() - started, 1),
          'code_changed_during_run': any(hashlib.sha256((root / n).read_bytes()).hexdigest() != h for n,h in hashes.items()),
          'provider_calls': 0,
          'limitations': 'Not the prior BYOK inputs: no model-assisted search/filter. Empty fake responses only serialize generation requests; verification/pruning/quality/cost are unmeasured. Live Wikipedia can change.'}
output = args.output
output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False))
