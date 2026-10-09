"""CPU provenance must pass before persisted evidence becomes eligible."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]

@pytest.fixture
def collector(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(APP / "cloudflare-preview"))
    spec = importlib.util.spec_from_file_location("gemini_measurement_check", APP / "cloudflare-preview/measure_gemini.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    (tmp_path / "edge-manifest.json").write_text(json.dumps({"bundle_sha256":"gateway","python_bundle_sha256":"python"}))
    original = Path.read_text
    secret_path = Path.home()/".local/state/ikimono-cloudflare-preview/secrets.json"
    monkeypatch.setattr(Path,"read_text",lambda path,*args,**kwargs: json.dumps({"IKIMONO_SESSION_SECRET":"synthetic"})
        if path==secret_path else original(path,*args,**kwargs))
    hashes = {module.PATHS[0]:"a"*64,module.PATHS[1]:"b"*64}
    monkeypatch.setattr(module.subprocess,"run",lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps(hashes)))
    return module,tmp_path,hashes


def evidence(module, hashes):
    return {"complete":True,"eligible_for_success_cpu_comparison":True,
        "subscription_probe":{"path":"/health","preview_bundle_sha256":"gateway","preview_backend_bundle_sha256":"python"},
        "records":[{"path":path,"preview_bundle_sha256":"gateway","preview_gemini_engine":"javascript",
                    "sha256":digest,"cpu_ms":1,"isolate_invocation":2} for path,digest in hashes.items()]}


def test_missing_trace_is_retained_and_ineligible(collector,monkeypatch):
    module,tmp_path,hashes=collector
    partial=evidence(module,hashes);partial["complete"]=False;partial["eligible_for_success_cpu_comparison"]=False
    monkeypatch.setattr(module,"measure",lambda *args,**kwargs:partial)
    output=tmp_path/"missing.json"
    with pytest.raises(AssertionError,match="Incomplete CPU evidence"):module.collect(1,output)
    stored=json.loads(output.read_text())
    assert stored["records"]==partial["records"]
    assert stored["provenance_verified"] is False and stored["eligible_for_success_cpu_comparison"] is False


@pytest.mark.parametrize("failure",["engine","body","gateway","backend"])
def test_mismatched_provenance_never_persists_eligible(collector,monkeypatch,failure):
    module,tmp_path,hashes=collector
    wrong=evidence(module,hashes)
    if failure=="engine":wrong["records"][0]["preview_gemini_engine"]="python"
    elif failure=="body":wrong["records"][0]["sha256"]="c"*64
    elif failure=="gateway":wrong["records"][0]["preview_bundle_sha256"]="stale"
    else:wrong["subscription_probe"]["preview_backend_bundle_sha256"]="stale"
    monkeypatch.setattr(module,"measure",lambda *args,**kwargs:wrong)
    output=tmp_path/"mismatch.json"
    with pytest.raises(AssertionError):module.collect(1,output)
    stored=json.loads(output.read_text())
    assert stored["records"]==wrong["records"]
    assert stored["provenance_verified"] is False and stored["eligible_for_success_cpu_comparison"] is False
