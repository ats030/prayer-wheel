"""Account CPU for protected synthetic serialization/streaming, no AI."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("preview_cpu", HERE.parent / "cloudflare-preview/measure_cpu.py")
sys.path.insert(0, str(HERE.parent / "cloudflare-preview"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
PATHS = ("/health", "/payload/1", "/payload/3", "/wire/1", "/wire/3")


def request_factory(path):
    if path == "/health":
        return {}
    kind, count = path.strip("/").split("/")
    fixtures = HERE / "fixtures"
    if kind == "payload":
        body = (fixtures / f"multipart-{count}.bin").read_bytes()
        mime = (fixtures / f"multipart-{count}.type").read_text()
    else:
        body = (fixtures / f"wire-{count}.json").read_bytes()
        mime = "application/json"
    return {"method": "POST", "data": body, "headers": {"Content-Type": mime}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.samples <= 5:
        parser.error("Use 1 to 5 subsequent samples")
    result = {}
    try:
        provenance = json.loads((HERE / "fixtures/provenance.json").read_text())
        builder_spec = importlib.util.spec_from_file_location("app_probe_builder", HERE.parent / "cloudflare-app-probe/build.py")
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        expected_provider = builder.bundle_digest(json.loads((builder.HERE / "manifest.json").read_text()))
        assert provenance["python_bundle_sha256"] == expected_provider, "Stale provider fixture"
        assert provenance["template_sha256"] == hashlib.sha256((HERE / "fixtures/template.json").read_bytes()).hexdigest(), "Changed template fixture"
        for name, digest in provenance["fixtures"].items():
            assert hashlib.sha256((HERE / "fixtures" / name).read_bytes()).hexdigest() == digest, "Changed request fixture"
        result = collector.measure(args.samples, origin="https://ikimono-note-transport-preview.ats030.workers.dev",
                                   paths=PATHS, request_factory=request_factory, wrangler_config=HERE / "remote.jsonc")
        wire_hashes = {count: hashlib.sha256((HERE / "fixtures" / f"wire-{count}.json").read_bytes()).hexdigest() for count in (1, 3)}
        photo_hash = hashlib.sha256((HERE.parent / "cloudflare-app-probe/profile-fixtures/noise.jpg").read_bytes()).hexdigest()
        for row in result["records"]:
            if row["path"].startswith("/wire/") and row["status"] == 200:
                assert row["sha256"] == wire_hashes[int(row["path"].rsplit("/", 1)[1])], "Streaming changed provider bytes"
            elif row["path"].startswith("/payload/") and row["status"] == 200:
                count = int(row["path"].rsplit("/", 1)[1])
                expected = {"probe": {"sha256": [photo_hash] * count},
                            "wire_bytes": (HERE / "fixtures" / f"wire-{count}.json").stat().st_size,
                            "wire_sha256": wire_hashes[count], "network_calls": 0}
                expected_bytes = json.dumps(expected, separators=(",", ":")).encode()
                assert row["sha256"] == hashlib.sha256(expected_bytes).hexdigest(), "Serialization changed provider payload"
        result["source_sha256"] = hashlib.sha256((HERE / "worker.mjs").read_bytes()).hexdigest()
        result["remote_wrapper_sha256"] = hashlib.sha256((HERE / "remote.mjs").read_bytes()).hexdigest()
        for row in [result["subscription_probe"], *result["records"]]:
            assert row.get("transport_source_sha256") == result["source_sha256"], "Stale transport source"
            assert row.get("transport_wrapper_sha256") == result["remote_wrapper_sha256"], "Stale wrapper source"
        result["network_calls"] = 0
        result["python_bundle_sha256"] = expected_provider
        result["scope"] = "synthetic only; excludes app authentication, input validation, AI and persistence"
    except (RuntimeError, OSError, AssertionError) as error:
        result.update({"eligible_for_success_cpu_comparison": False, "failure_type": type(error).__name__})
        result.setdefault("complete", False)
        result.setdefault("records", [])
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["eligible_for_success_cpu_comparison"]:
        print("FAIL: incomplete, invalid or byte-mismatched CPU evidence")
        raise SystemExit(2)
    for path in PATHS:
        rows = [r for r in result["records"] if r["path"] == path]
        print(path, [(r["cpu_ms"], r["isolate_invocation"]) for r in rows])
