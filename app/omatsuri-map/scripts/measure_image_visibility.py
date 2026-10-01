#!/usr/bin/env python3
"""Measure festival image visibility across the three fetch paths.

before = path B (ja.wikipedia pageimages) -> path A (Wikidata P18)
after  = path B -> path C (Commons search, exact-name) -> path A

A festival counts as "visible" on a path when the response carries both an
image URL and a non-empty license, matching the frontend's own display rule
(`!result.license` -> hidden). Output goes to data/photo_coverage.json.

Usage:
    python3 scripts/measure_image_visibility.py                 # full run
    python3 scripts/measure_image_visibility.py --limit 10      # smoke run
"""
import argparse
import concurrent.futures as cf
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("OMATSURI_MAP_BASE", "http://localhost:8527")
UA = "omatsuri-map/1.0 (https://github.com/ats030/omatsuri-map) measure-script"


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return json.load(resp)


def path_b(festival):
    title = festival.get("wikipedia_title") or ("")
    if not title:
        if not festival.get("qid"):
            return None
        title = festival.get("label_ja") or ""
    if not title:
        return None
    url = f"{BASE}/api/wiki/content?title={urllib.parse.quote(title)}&qid={urllib.parse.quote(festival.get('qid') or '')}"
    data = get_json(url)
    image = data.get("image_url")
    license_ = (data.get("license") or "").strip()
    if image and license_:
        return {"path": "B", "url": image, "license": license_}
    return None


def path_c(festival):
    label = (festival.get("label_ja") or "").strip()
    if not label:
        return None
    url = (
        f"{BASE}/api/commons/image?label={urllib.parse.quote(label)}"
        f"&prefecture={urllib.parse.quote(festival.get('prefecture') or '')}"
    )
    data = get_json(url)
    image = data.get("image_url")
    license_ = (data.get("license") or "").strip()
    if image and license_:
        return {"path": "C", "url": image, "license": license_, "artist": data.get("artist") or "", "credit": data.get("credit") or ""}
    return None


def path_a(festival):
    qid = festival.get("qid")
    if not qid:
        return None
    url = f"{BASE}/api/wiki/image?qid={urllib.parse.quote(qid)}"
    data = get_json(url)
    image = data.get("url")
    license_ = (data.get("license") or "").strip()
    if image and license_:
        return {"path": "A", "url": image, "license": license_}
    return None


def attempt(fn, festival):
    try:
        return fn(festival)
    except Exception:
        return None


def resolve(festival, order):
    """Try paths in `order`; return (winning_path_or_None, per_path_results)."""
    fns = {"B": path_b, "C": path_c, "A": path_a}
    results = {}
    for p in order:
        r = attempt(fns[p], festival)
        results[p] = bool(r)
        if r:
            return p, dict(r, results=results)
    return None, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "data", "photo_coverage.json"))
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "frontend", "festivals.json"), encoding="utf-8") as fh:
        festivals = json.load(fh)

    if args.limit:
        festivals = festivals[: args.limit]

    before_order = ["B", "A"]
    after_order = ["B", "C", "A"]

    def work(item):
        idx, f = item
        b = attempt(path_b, f)
        a = attempt(path_a, f) if not b else None
        before_path = "B" if b else ("A" if a else None)
        before = b or a

        if b:
            # B already wins; C is not consulted either way.
            after_path, after = "B", b
        else:
            c = attempt(path_c, f)
            a2 = a if a is not None else attempt(path_a, f)
            if c:
                after_path, after = "C", c
            elif a2:
                after_path, after = "A", a2
            else:
                after_path, after = None, {}
        return idx, f, before_path, before, after_path, after

    rows = [None] * len(festivals)
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for idx, f, bp, bres, ap_, ares in ex.map(work, list(enumerate(festivals))):
            rows[idx] = {
                "qid": f.get("qid"),
                "label_ja": f.get("label_ja"),
                "prefecture": f.get("prefecture"),
                "before_path": bp,
                "before": bres,
                "after_path": ap_,
                "after": ares,
            }

    total = len(rows)
    before_visible = sum(1 for r in rows if r["before_path"])
    after_visible = sum(1 for r in rows if r["after_path"])

    def dist(path_key):
        d = {"B": 0, "C": 0, "A": 0, "none": 0}
        for r in rows:
            d[r[path_key] or "none"] += 1
        return d

    out_path = os.path.normpath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = {
        "generated_by": "scripts/measure_image_visibility.py",
        "base": BASE,
        "total": total,
        "before": {
            "order": before_order,
            "visible": before_visible,
            "rate": round(before_visible / total, 4) if total else 0,
            "path_distribution": dist("before_path"),
        },
        "after": {
            "order": after_order,
            "visible": after_visible,
            "rate": round(after_visible / total, 4) if total else 0,
            "path_distribution": dist("after_path"),
        },
        "delta_visible": after_visible - before_visible,
        "delta_rate": round((after_visible - before_visible) / total, 4) if total else 0,
        "festivals": rows,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"total={total}")
    print(f"before visible={before_visible} rate={payload['before']['rate']} dist={payload['before']['path_distribution']}")
    print(f"after  visible={after_visible} rate={payload['after']['rate']} dist={payload['after']['path_distribution']}")
    print(f"delta  visible=+{payload['delta_visible']} rate=+{payload['delta_rate']}")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
