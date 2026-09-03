#!/usr/bin/env python3
import importlib.util
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


MODULE_PATH = Path(__file__).with_name("visit-log") / "main.py"
spec = importlib.util.spec_from_file_location("visit_log_main", MODULE_PATH)
visit_log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visit_log)


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    visit_log.DATA_DIR = data
    visit_log.SALT_PATH = data / "salt"
    visit_log.SITES_PATH = data / "sites.json"
    visit_log._salt = None
    visit_log.save_sites([
        {"name": "note", "url": "https://note.example/user", "note": ""},
        {"name": "local", "url": "http://ubuntu-server-app:8500/", "note": ""},
    ])
    client = TestClient(visit_log.app)

    response = client.get(
        "/go/note",
        headers={"user-agent": "selftest-agent", "referer": "https://source.example/private?q=1"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "https://note.example/user"

    response = client.get("/go/missing", follow_redirects=False)
    assert response.status_code == 404

    summary = client.get("/api/summary?days=30").json()
    assert summary["total_views"] == 0
    assert summary["total_outbound"] == 1
    assert summary["outbound"] == [{"key": "note", "clicks": 1, "visitors": 1}]
    sites = {row["key"]: row for row in summary["sites"]}
    assert sites["note"]["tracked_url"] == "/go/note"
    assert sites["local"]["tracked_url"] == ""

    raw = next(data.glob("outbound-*.jsonl")).read_text(encoding="utf-8")
    row = json.loads(raw)
    assert row["ref"] == "source.example"
    assert "selftest-agent" not in raw
    assert "127.0.0.1" not in raw

    client.get("/go/note", headers={"dnt": "1"}, follow_redirects=False)
    assert len(next(data.glob("outbound-*.jsonl")).read_text().splitlines()) == 1

print("OK: outbound click tracking")
