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

FETCH_PATH = MODULE_PATH.with_name("fetch-cloud-run-stats.py")
fetch_spec = importlib.util.spec_from_file_location("visit_log_cloud_stats", FETCH_PATH)
cloud_stats = importlib.util.module_from_spec(fetch_spec)
fetch_spec.loader.exec_module(cloud_stats)


with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp)
    visit_log.DATA_DIR = data
    visit_log.SALT_PATH = data / "salt"
    visit_log.SITES_PATH = data / "sites.json"
    visit_log.EXTERNAL_STATS_PATH = data / "external-stats.json"
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
    assert summary["external_stats"] == []

    response = client.post("/api/external-stats", json={
        "site": "note", "value": 123, "metric": "全体ビュー",
    })
    assert response.status_code == 200
    summary = client.get("/api/summary?days=30").json()
    assert summary["external_stats"] == [{
        "site": "note", "value": 123, "metric": "全体ビュー", "source": "manual",
        "observed_at": response.json()["observed_at"], "status": "ok",
    }]
    assert client.post("/api/external-stats", json={"site": "note", "value": -1}).status_code == 400

    raw = next(data.glob("outbound-*.jsonl")).read_text(encoding="utf-8")
    row = json.loads(raw)
    assert row["ref"] == "source.example"
    assert "selftest-agent" not in raw
    assert "127.0.0.1" not in raw

    client.get("/go/note", headers={"dnt": "1"}, follow_redirects=False)
    assert len(next(data.glob("outbound-*.jsonl")).read_text().splitlines()) == 1

    cloud_stats.access_token = lambda _: "test-token"
    totals = {"ikimono-note": 25, "dekita": 12}
    cloud_stats.request_total = lambda target, _: totals[target["site"]]
    rows = cloud_stats.update(visit_log.EXTERNAL_STATS_PATH, "unused-gcloud")
    by_site = {row["site"]: row for row in rows}
    assert by_site["note"]["value"] == 123
    assert by_site["ikimono-note"]["value"] == 25
    assert by_site["dekita"]["source"] == "cloud-monitoring"

print("OK: outbound click tracking and external official stats")
