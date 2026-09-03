#!/usr/bin/env python3
"""Cloud MonitoringのCloud Run request_count累計をvisit-logへ保存する。"""
import argparse
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TARGETS = (
    {"site": "ikimono-note", "project": "ikimono-note-12205", "service": "ikimono-note"},
    {"site": "dekita", "project": "dekita-507214", "service": "dekita-app"},
)

def access_token(gcloud: str) -> str:
    return subprocess.run([gcloud, "auth", "print-access-token", "--quiet"], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()

def request_total(target: dict, token: str, opener=urllib.request.urlopen) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    params = {"filter": ('metric.type="run.googleapis.com/request_count" AND '
                          'resource.type="cloud_run_revision" AND '
                          'resource.labels.service_name="{}"'.format(target["service"])),
              "interval.startTime": "2026-01-01T00:00:00Z", "interval.endTime": now,
              "aggregation.alignmentPeriod": "86400s",
              "aggregation.perSeriesAligner": "ALIGN_SUM",
              "aggregation.crossSeriesReducer": "REDUCE_SUM", "view": "FULL", "pageSize": "1000"}
    base = "https://monitoring.googleapis.com/v3/projects/{}/timeSeries?".format(target["project"])
    total = 0
    while True:
        request = urllib.request.Request(base + urllib.parse.urlencode(params),
                                         headers={"Authorization": "Bearer " + token})
        with opener(request, timeout=30) as response:
            payload = json.load(response)
        for series in payload.get("timeSeries", []):
            for point in series.get("points", []):
                value = point.get("value", {})
                total += int(value.get("int64Value", value.get("doubleValue", 0)))
        page = payload.get("nextPageToken")
        if not page:
            return total
        params["pageToken"] = page

def update(output: Path, gcloud: str) -> list[dict]:
    token = access_token(gcloud)
    try:
        rows = json.loads(output.read_text(encoding="utf-8")) if output.exists() else []
    except (json.JSONDecodeError, OSError):
        rows = []
    by_site = {r.get("site"): r for r in rows if isinstance(r, dict) and r.get("site")}
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors = []
    for target in TARGETS:
        try:
            by_site[target["site"]] = {"site": target["site"],
                "value": request_total(target, token), "metric": "HTTPリクエスト",
                "source": "cloud-monitoring", "observed_at": observed_at, "status": "ok"}
        except Exception as exc:
            errors.append("{}: {}".format(target["site"], exc))
            if target["site"] in by_site:
                by_site[target["site"]]["status"] = "取得失敗"
                by_site[target["site"]]["last_error_at"] = observed_at
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(json.dumps(list(by_site.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(output)
    if errors:
        raise RuntimeError("; ".join(errors))
    return list(by_site.values())

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path.home() / "data/visit-log/external-stats.json")
    parser.add_argument("--gcloud", default=str(Path.home() / "google-cloud-sdk/bin/gcloud"))
    args = parser.parse_args()
    print(json.dumps(update(args.output, args.gcloud), ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
