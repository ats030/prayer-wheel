"""Live source/model validation, never fixtures. Does not save query results."""
import json
import sys
import time
from timeline import MAX_EVENTS, build_timeline, parse_query

query = parse_query(" ".join(sys.argv[1:]) or "コーヒー")
started = time.monotonic()
def emit(record):
    print(json.dumps(record, ensure_ascii=False), flush=True)
result = build_timeline(query, emit)
emit(result)
assert result["events"], "No grounded events returned"
assert len(result["events"]) <= MAX_EVENTS
assert result["events"] == sorted(result["events"], key=lambda e: e["year"])
assert all(query.start is None or e["year"] >= query.start for e in result["events"])
assert all(query.end is None or e["year"] <= query.end for e in result["events"])
print(f"PASS: {len(result['events'])} events, {time.monotonic() - started:.1f}s", flush=True)
