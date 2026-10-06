#!/usr/bin/env python3
"""Read existing Cloud Run request logs; persist aggregates only, never raw entries."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import fcntl
import json
import re
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")
DATA = Path.home() / "data/visit-log"
STATIC_SUFFIXES = {"css", "js", "mjs", "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "woff", "woff2", "ttf", "map", "avif"}


def stamp(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


class Google:
    def __init__(self, gcloud):
        self.token = subprocess.run([gcloud, "auth", "print-access-token", "--quiet"],
                                    check=True, capture_output=True, text=True, timeout=45).stdout.strip()
        self.last_call = 0

    def request(self, url, body=None):
        # entries.list permits 60 calls/min/project. Pace all calls conservatively.
        for attempt in range(4):
            time.sleep(max(0, 1.1 - (time.monotonic() - self.last_call)))
            self.last_call = time.monotonic()
            req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": "Bearer " + self.token,
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=45) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                    # Do not persist Google response bodies: they may contain user data.
                    raise RuntimeError(f"Google API HTTP {exc.code}") from None
                time.sleep(2 ** attempt)

    def services(self, project):
        rows, page = [], ""
        while True:
            url = f"https://run.googleapis.com/v2/projects/{project}/locations/-/services?pageSize=100"
            if page:
                from urllib.parse import quote
                url += "&pageToken=" + quote(page, safe="")
            payload = self.request(url)
            rows.extend(payload.get("services", []))
            page = payload.get("nextPageToken")
            if not page:
                return rows

    def retention(self, project):
        payload = self.request(f"https://logging.googleapis.com/v2/projects/{project}/locations/global/buckets/_Default")
        return int(payload.get("retentionDays", 30))

    def entries(self, project, service, region, start, end):
        body = {"resourceNames": [f"projects/{project}"], "pageSize": 1000,
                "orderBy": "timestamp asc", "filter":
                'resource.type="cloud_run_revision" AND log_id("run.googleapis.com/requests") '
                f'AND resource.labels.service_name={json.dumps(service)} '
                f'AND resource.labels.location={json.dumps(region)} '
                f'AND timestamp>={json.dumps(stamp(start))} AND timestamp<{json.dumps(stamp(end))}'}
        pages = set()
        for _ in range(500):
            payload = self.request("https://logging.googleapis.com/v2/entries:list", body)
            yield from payload.get("entries", [])
            page = payload.get("nextPageToken")
            if not page:
                return
            if page in pages:
                raise RuntimeError("繰り返しページを検出")
            pages.add(page)
            body["pageToken"] = page
        raise RuntimeError("取得ページ上限に到達（集計は更新しません）")


def category(path, method, config):
    def matches(prefixes):
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)
    if matches(config.get("api_prefixes", [])) or method not in {"GET", "HEAD"}:
        return "api"
    if matches(config.get("static_prefixes", [])) or path.rsplit(".", 1)[-1].lower() in STATIC_SUFFIXES:
        return "static"
    return "page"


def safe_path(value):
    """Collapse common identifiers and credential-bearing routes before storage."""
    raw = urlsplit(value).path or "/"
    segments = raw.split("/")
    result = []
    private_next = False
    for segment in segments:
        decoded = unquote(segment)
        sensitive = (private_next or "@" in decoded or decoded.isdigit()
                     or bool(re.fullmatch(r"[0-9a-fA-F-]{24,}", decoded))
                     or bool(re.fullmatch(r"[A-Za-z0-9_=-]{24,}", decoded))
                     or any(ord(c) < 32 for c in decoded))
        result.append(":id" if sensitive else segment)
        private_next = decoded.lower() in {"token", "reset", "verify", "session", "users", "user", "invite", "auth"}
    return "/".join(result)[:300]


def aggregate(entries, config):
    counts = Counter()
    for entry in entries:
        http = entry.get("httpRequest", {})
        if not http or not entry.get("timestamp"):
            raise ValueError("アクセスログに必要な項目がありません")
        day = parse(entry["timestamp"]).astimezone(TZ).date().isoformat()
        path = safe_path(http.get("requestUrl", ""))
        # Strip userinfo, host, query, fragments; never retain UA, IP, trace, insertId.
        path = path[:300]
        ua = http.get("userAgent", "").lower()
        bot = "bot" if any(w in ua for w in ("bot", "crawler", "spider", "headless")) else "unknown"
        status = int(http.get("status", 0))
        counts[(day, path, category(path, http.get("requestMethod", "GET"), config), status, bot)] += 1
    return [dict(date=k[0], path=k[1], kind=k[2], status=k[3], bot=k[4], requests=n)
            for k, n in sorted(counts.items())]


def merge_coverage(intervals, start, end, cutoff):
    spans = sorted([(parse(a), parse(b)) for a, b in intervals] + [(start, end)])
    merged = []
    for a, b in spans:
        if a >= b or b.astimezone(TZ).date().isoformat() < cutoff:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [[stamp(a), stamp(b)] for a, b in merged]


def update(output, config, google, now=None):
    now = now or datetime.now(timezone.utc)
    end = now - timedelta(minutes=5)  # allow request logs to arrive
    today = now.astimezone(TZ).date()
    cutoff = (today - timedelta(days=89)).isoformat()
    state = read_json(output, {"version": 1, "services": [], "projects": {}})
    previous = {r["id"]: r for r in state["services"]}
    for row in previous.values():
        row["rows"] = [r for r in row.get("rows", []) if r["date"] >= cutoff]
        for r in row["rows"]:
            r["path"] = safe_path(r["path"])
    active = {}
    errors = []
    projects = {}
    for project in config["projects"]:
        try:
            services = google.services(project)
            retention = google.retention(project)
            projects[project] = {"status": "ok", "retention_days": retention, "attempted_at": stamp(now)}
        except Exception as exc:
            projects[project] = {**state.get("projects", {}).get(project, {}),
                                 "status": "取得失敗", "attempted_at": stamp(now), "error": type(exc).__name__}
            errors.append(project)
            for key, row in previous.items():
                if row["project"] == project and key not in config.get("exclude", []):
                    active[key] = {**row, "status": "取得失敗", "attempted_at": stamp(now)}
            continue
        discovered = {s["name"] for s in services}
        for key, old in previous.items():
            identity = f'projects/{project}/locations/{old["region"]}/services/{old["service"]}'
            if old["project"] == project and identity not in discovered and old.get("rows") and key not in config.get("exclude", []):
                services.append({"name": identity, "uri": old.get("url", ""), "retired": True})
        for service in services:
            parts = service["name"].split("/")
            region, name = parts[3], parts[5]
            key = f"{project}/{region}/{name}"
            if key in config.get("exclude", []):
                continue
            old = previous.get(key, {})
            row = {**old, "id": key, "project": project, "region": region, "service": name,
                   "url": service.get("uri", ""), "attempted_at": stamp(now),
                   "discovery_state": "retired" if service.get("retired") else "active"}
            retention_start = now - timedelta(days=min(90, retention))
            if old.get("observed_at"):
                refresh_day = parse(old["observed_at"]).astimezone(TZ).date() - timedelta(days=2)
                start = max(retention_start, datetime.combine(refresh_day, datetime.min.time(), TZ))
                # Boundary-day aggregates cannot be split. Query after the previous end
                # to keep that day's saved prefix without double-counting it.
                if start == retention_start:
                    start = max(start, parse(old["observed_at"]))
            else:
                start = retention_start
                if service.get("createTime"):
                    start = max(start, parse(service["createTime"]))
            try:
                rows = aggregate(google.entries(project, name, region, start, end), config) if start < end else []
                refresh_date = start.astimezone(TZ).date().isoformat()
                kept = [r for r in old.get("rows", []) if cutoff <= r["date"] < refresh_date]
                if old.get("observed_at") and parse(old["observed_at"]) <= start:
                    kept += [r for r in old.get("rows", []) if r["date"] == refresh_date]
                row.update(rows=kept + [r for r in rows if r["date"] >= cutoff], status="ok",
                           observed_at=stamp(end), coverage_start=old.get("coverage_start", stamp(start)),
                           coverage=merge_coverage(old.get("coverage", []), start, end, cutoff),
                           retention_days=retention)
                row.pop("error", None)
            except Exception as exc:
                row.update(status="取得失敗", error=type(exc).__name__)
                errors.append(key)
            active[key] = row
            print(json.dumps({"service": key, "status": row["status"],
                              "requests": sum(r["requests"] for r in row.get("rows", []))}), flush=True)
    state = {"version": 1, "attempted_at": stamp(now), "projects": projects,
             "services": sorted(active.values(), key=lambda r: r["id"])}
    save(output, state)
    return state, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("cloud-run-config.json"))
    parser.add_argument("--output", type=Path, default=DATA / "cloud-run-stats.json")
    parser.add_argument("--gcloud", default=str(Path.home() / "google-cloud-sdk/bin/gcloud"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            state, errors = update(args.output, read_json(args.config, {}), Google(args.gcloud))
        except Exception as exc:
            state = read_json(args.output, {"version": 1, "services": [], "projects": {}})
            state.update(attempted_at=stamp(datetime.now(timezone.utc)), status="取得失敗", error=type(exc).__name__)
            save(args.output, state)
            raise
        print(json.dumps({"services": len(state["services"]), "failed": errors}, ensure_ascii=False))
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
