#!/usr/bin/env python3
"""Build frontend/geo/geoparks.json: coarse geopark outlines plus the number of each kind inside them.

Membership is counted against the full geo.db boundary; only the drawn outline is simplified further.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# About 500 m: enough to read a region outline at prefecture zoom while keeping the file small.
DISPLAY_TOLERANCE = 0.005
POINTS = {"shiseki": ("shiseki/shiseki.db", "shiseki", "latitude", "longitude"),
          "omatsuri": ("omatsuri/festivals.db", "festival", "latitude", "longitude"),
          "onsen": ("onsen/onsen.db", "onsen", "latitude", "longitude"),
          "tokusan": ("tokusan/tokusan.db", "tokusan", "lat", "lng")}


def polygons(geometry: dict) -> list:
    return geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]


def inside_ring(x: float, y: float, ring: list) -> bool:
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def contains(geometry: dict, x: float, y: float) -> bool:
    return any(inside_ring(x, y, rings[0]) and not any(inside_ring(x, y, hole) for hole in rings[1:])
               for rings in polygons(geometry))


def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker on one closed ring; the caller drops rings that collapse."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (x1, y1), (x2, y2) = points[start], points[end]
        dx, dy = x2 - x1, y2 - y1
        length = (dx * dx + dy * dy) ** 0.5
        best, index = 0.0, None
        for i in range(start + 1, end):
            px, py = points[i]
            d = abs(dy * (px - x1) - dx * (py - y1)) / length if length else ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
            if d > best:
                best, index = d, i
        if index is not None and best > tolerance:
            keep[index] = True
            stack += [(start, index), (index, end)]
    return [[round(x, 4), round(y, 4)] for (x, y), k in zip(points, keep) if k]


def outline(geometry: dict) -> dict:
    out = []
    for rings in polygons(geometry):
        shell = simplify(rings[0], DISPLAY_TOLERANCE)
        if len(shell) < 4:
            continue
        out.append([shell] + [h for h in (simplify(r, DISPLAY_TOLERANCE) for r in rings[1:]) if len(h) >= 4])
    if not out:  # A region made only of small islands keeps its largest original polygon.
        out = [max(polygons(geometry), key=lambda rings: len(rings[0]))]
    return {"type": "MultiPolygon", "coordinates": out}


def build(data: Path) -> dict:
    with closing(sqlite3.connect(f"file:{data / 'geo/geo.db'}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        meta = dict(con.execute("select key, value from meta").fetchall())
        regions = [dict(r) for r in con.execute("select * from geopark where geometry is not null order by slug")]
    points = {}
    for kind, (db, table, lat, lng) in POINTS.items():
        with closing(sqlite3.connect(f"file:{data / db}?mode=ro", uri=True)) as source:
            points[kind] = source.execute(f"select {lng}, {lat} from {table} where {lat} is not null and {lng} is not null").fetchall()
    features = []
    for r in regions:
        geometry = json.loads(r["geometry"])
        counts = {kind: sum(1 for x, y in rows if r["min_lon"] <= x <= r["max_lon"] and r["min_lat"] <= y <= r["max_lat"]
                            and contains(geometry, x, y)) for kind, rows in points.items()}
        members = json.loads(r["municipalities"])
        features.append({"type": "Feature", "geometry": outline(geometry), "properties": {
            "slug": r["slug"], "name": r["name"], "unesco": bool(r["unesco"]), "certified": r["certified"],
            "municipalities": [m["name"] for m in members if not m["partial"]],
            "partial": [m["name"] for m in members if m["partial"]],
            "counts": counts, "source": r["source_url"], "fetched": r["fetched"]}})
    return {"type": "FeatureCollection", "features": features,
            "meta": {"source": meta["geopark_source"], "boundary": meta["boundary_source"], "built": meta["built"]}}


def render(data: Path) -> str:
    return json.dumps(build(data), ensure_ascii=False, separators=(",", ":")) + "\n"


def main():
    target = ROOT / "frontend/geo/geoparks.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(ROOT / "data"))
    collection = json.loads(target.read_text())
    print(json.dumps({"geoparks": len(collection["features"]), "bytes": target.stat().st_size,
                      "points": sum(sum(f["properties"]["counts"].values()) for f in collection["features"])}))


if __name__ == "__main__":
    main()
