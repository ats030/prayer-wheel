"""One-time removal of demo users. Refuse to replace unknown custom accounts."""
import json
import re
import subprocess

from engine import PRIVATE, engine_client
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def harden():
    with engine_client(admin=True) as engine:
        response = engine.get("/_plugins/_security/api/internalusers")
        response.raise_for_status()
        names = set(response.json())
    expected = {"admin", "web_search_reader", "logstash", "snapshotrestore",
                "kibanaserver", "kibanaro", "readall", "anomalyadmin"}
    if names - expected:
        raise ValueError("Unknown custom users exist; refusing to replace users")
    original = subprocess.check_output(["docker", "exec", "web-search-opensearch", "cat",
        "/usr/share/opensearch/config/opensearch-security/internal_users.yml"], text=True)
    match = re.search(r'(?ms)^admin:\s*\n.*?^\s+hash:\s*"([^"\n]+)"', original)
    if not match:
        raise ValueError("Cannot locate generated admin hash")
    backup = PRIVATE / "bootstrap-internal-users.yml"
    if not backup.exists():
        backup.touch(mode=0o600)
        backup.write_text(original)
    users = PRIVATE / "internal-users.json"
    users.touch(mode=0o600, exist_ok=True)
    users.write_text(json.dumps({"_meta": {"type": "internalusers", "config_version": 2},
        "admin": {"hash": match[1], "reserved": True, "backend_roles": ["admin"]}}))
    subprocess.run(["docker", "cp", str(users), "web-search-opensearch:/tmp/web-search-users.json"],
                   check=True, capture_output=True)
    result = subprocess.run(["docker", "exec", "web-search-opensearch",
        "/usr/share/opensearch/plugins/opensearch-security/tools/securityadmin.sh",
        "-f", "/tmp/web-search-users.json", "-t", "internalusers", "-icl", "-nhnv",
        "-cacert", "/usr/share/opensearch/config/tls/server.pem",
        "-cert", "/usr/share/opensearch/config/kirk.pem",
        "-key", "/usr/share/opensearch/config/kirk-key.pem"],
        capture_output=True, text=True)
    if result.returncode or "SUCC" not in result.stdout:
        # The tool reports connectivity/certificate errors, never the input
        # user hashes. Bound diagnostic output to avoid large unrelated logs.
        diagnostic = (result.stdout + result.stderr)[-1500:]
        raise ValueError("Security initialization failed: " + diagnostic)
    spec = spec_from_file_location("ingest", Path(__file__).with_name("ingest-opensearch.py"))
    ingest = module_from_spec(spec)
    spec.loader.exec_module(ingest)
    with engine_client(admin=True) as engine:
        ingest.provision_reader(engine)
        response = engine.get("/_plugins/_security/api/internalusers")
        response.raise_for_status()
        if set(response.json()) != {"admin", "web_search_reader"}:
            raise ValueError("Unexpected remaining users")
    print("Only admin and web_search_reader remain; disable bootstrap admin DN now")


if __name__ == "__main__":
    harden()
