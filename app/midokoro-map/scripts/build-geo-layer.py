#!/usr/bin/env python3
"""Build frontend/geo/geoparks.json, geosites.json and nationalparks.json from geo.db.

geoparks.json: coarse geopark outlines plus the number of each kind inside them. Membership is counted against the
full geo.db boundary; the drawn outline is the topology-preserving display_geometry built by geo-map.
geosites.json: geological natural monuments; `shiseki` names the shiseki point that already shows one, so the shiseki
tab can hide it.
"""
import json
import math
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A geosite whose name equals a shiseki point this close is the same place (e.g. a 名勝・天然記念物 row).
NEAR_METERS = 1000
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
        features.append({"type": "Feature", "geometry": json.loads(r["display_geometry"]), "properties": {
            "slug": r["slug"], "name": r["name"], "unesco": bool(r["unesco"]), "certified": r["certified"],
            "municipalities": [m["name"] for m in members if not m["partial"]],
            "prefectures": sorted({m["prefecture"] for m in members if not m["partial"]}),
            "partial": [m["name"] for m in members if m["partial"]],
            "counts": counts, "source": r["source_url"], "fetched": r["fetched"]}})
    return {"type": "FeatureCollection", "features": features,
            "meta": {"source": meta["geopark_source"], "boundary": meta["boundary_source"], "built": meta["built"]}}


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKC", name)
    return re.sub(r"[\s・･]|\([^)]*\)", "", name)


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat1 - lat2) * 111_195, (lon1 - lon2) * 111_195 * math.cos(math.radians(lat1)))


def shown_by_shiseki(site: dict, by_heritage: dict, cells: dict) -> str | None:
    """Return the shiseki site_id that already shows this geosite: the same 文化庁 ID, or the same name within 1 km.

    Names must match exactly: a temple or spa that contains the monument's name (石山寺 / 石山寺硅灰石) is another heritage.
    """
    if (match := by_heritage.get("401/" + str(int(site["heritage_id"])))):
        return match
    name, lat, lon = normalize(site["name"]), site["latitude"], site["longitude"]
    cell = (round(lat * 100), round(lon * 100))
    # 0.01 degree of longitude is under 1 km north of about 26°N, so two cells either way cover NEAR_METERS.
    for dy in (-1, 0, 1):
        for dx in (-2, -1, 0, 1, 2):
            for site_id, label, y, x in cells.get((cell[0] + dy, cell[1] + dx), ()):
                if label == name and distance(lat, lon, y, x) <= NEAR_METERS:
                    return site_id
    return None


def build_sites(data: Path) -> dict:
    with closing(sqlite3.connect(f"file:{data / 'geo/geo.db'}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        meta = dict(con.execute("select key, value from meta").fetchall())
        sites = [dict(r) for r in con.execute("select * from geosite order by heritage_id")]
    with closing(sqlite3.connect(f"file:{data / 'shiseki/shiseki.db'}?mode=ro", uri=True)) as con:
        rows = con.execute("select site_id, label_ja, latitude, longitude, heritage_id from shiseki").fetchall()
    by_heritage = {h: site_id for site_id, _, _, _, h in rows if h}
    cells = {}
    for site_id, label, lat, lon, _ in rows:
        if lat is not None and lon is not None:
            cells.setdefault((round(lat * 100), round(lon * 100)), []).append((site_id, normalize(label or ""), lat, lon))
    features, shared, missing = [], {}, 0
    for site in sites:
        if site["latitude"] is None or site["longitude"] is None:
            missing += 1
            continue
        if (site_id := shown_by_shiseki(site, by_heritage, cells)):
            shared[site["heritage_id"]] = site_id
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [site["longitude"], site["latitude"]]},
                         "properties": {key: site[key] for key in ("heritage_id", "name", "designation", "designation_label",
                                                                   "kind", "criteria", "prefecture", "address",
                                                                   "source_url", "fetched")}
                                        | {"shiseki": site_id}})
    return {"type": "FeatureCollection", "features": features,
            "meta": {"source": meta["geosite_source"], "built": meta["geosite_built"], "geosites": len(sites),
                     "without_coordinates": missing, "shown_by_shiseki": shared}}


def dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def build_nationalparks(data: Path) -> dict:
    with closing(sqlite3.connect(f"file:{data / 'geo/geo.db'}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(row) for row in con.execute('select * from nationalpark order by slug')]
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': json.loads(row.pop('display_geometry')), 'properties': row}
        for row in rows], 'meta': {'source': 'https://eadas.env.go.jp/eiadb/ebidbs/Service/About?title=Gis',
                                 'processing': 'midokoro-mapが区域を結合し表示用に簡略化'}}


def render(data: Path) -> dict[str, str]:
    return {"geoparks.json": dumps(build(data)), "geosites.json": dumps(build_sites(data)),
            "nationalparks.json": dumps(build_nationalparks(data))}


def main():
    target = ROOT / "frontend/geo"
    target.mkdir(parents=True, exist_ok=True)
    for name, text in render(ROOT / "data").items():
        (target / name).write_text(text)
    parks, sites = (json.loads((target / name).read_text()) for name in ("geoparks.json", "geosites.json"))
    print(json.dumps({"geoparks": len(parks["features"]), "bytes": (target / "geoparks.json").stat().st_size,
                      "points": sum(sum(f["properties"]["counts"].values()) for f in parks["features"]),
                      "geosites": len(sites["features"]), "geosites_shown_by_shiseki": len(sites["meta"]["shown_by_shiseki"]),
                      "geosites_without_coordinates": sites["meta"]["without_coordinates"],
                      "nationalparks": len(json.loads((target / 'nationalparks.json').read_text())['features'])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
