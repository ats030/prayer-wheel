"""Compare Workers quality results with native references; report local wall times."""
import json
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

fixtures = Path(__file__).resolve().parent / "fixtures"
reference = json.loads((fixtures / "expected.json").read_text())


def post(route, raw):
    request = Request(f"http://127.0.0.1:8790/{route}", raw,
                      {"Content-Type": "application/octet-stream"})
    with urlopen(request, timeout=60) as response:
        assert response.status == 200
        return json.load(response)


timings = []
for name, expected in reference["photos"].items():
    for repetition in range(3):
        result = post("measure", (fixtures / f"{name}.jpg").read_bytes())
        assert result["ok"] and result["jpeg_bytes"] > 0, result
        assert result["source_hashes"] == reference["source_hashes"], result
        assert result["quality"] == expected, (name, result, expected)
        assert result["quality_wall_ms"] >= 0 and result["prepare_wall_ms"] >= 0, result
        timings.append({"name": name, "repetition": repetition,
                        "quality_wall_ms": result["quality_wall_ms"],
                        "prepare_wall_ms": result["prepare_wall_ms"]})
    result = post("zip", (fixtures / f"{name}.zip").read_bytes())
    assert result["ok"] and result["name"] == f"{name}.jpg", result
    assert result["mime"] == "image/jpeg", result
    assert result["bytes"] == (fixtures / f"{name}.jpg").stat().st_size, result
    assert result["sha256"] == sha256((fixtures / f"{name}.jpg").read_bytes()).hexdigest(), result
for name in ("multiple", "traversal"):
    result = post("zip", (fixtures / f"{name}.zip").read_bytes())
    assert result["ok"] is False and result["error"], result
result = post("zip", b"not a zip")
assert result["ok"] is False
print(json.dumps({"local_wall_timings": timings}, indent=2))
print("PASS: native quality parity, source hashes, image preparation, ZIP extraction and rejection")
