"""座標を、生きものの居場所として意味のある言葉に変える。

緯度経度そのものは VLM にとってただの数字で、分布の知識と結びつきにくい。
「標高1200mの森林」「標高5mの水辺」に直せば、種を絞る手がかりになる。

使うのはどちらも登録不要・無料のオープンデータ。

- 標高: 国土地理院 標高API (政府標準利用規約。出典の明示が要る)
- 土地利用: OpenStreetMap Overpass API (ODbL。出典の明示が要る)

  uv run --with httpx python eval/add_geo_context.py

相手のサーバーに負担をかけないよう、1件ずつ間を空けて引く。100件で5分ほどかかる。
"""

from __future__ import annotations

import collections
import json
import time
from pathlib import Path

import httpx

MANIFEST = Path(__file__).parent / "dataset.json"
ELEVATION_API = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"
OVERPASS_API = "https://overpass-api.de/api/interpreter"
USER_AGENT = "IkimonoNote-eval/1.0 (https://github.com/ats030/ikimono-note)"

# OSM のタグを、生きものの居場所として意味のある言葉に直す。
# 原語のまま渡すと、VLM が読み解く余地に頼ることになる。
PLACE_WORDS = {
    "natural=water": "水辺", "natural=wetland": "湿地", "natural=wood": "森林",
    "natural=scrub": "低木林", "natural=grassland": "草地", "natural=beach": "砂浜",
    "natural=coastline": "海岸", "natural=bare_rock": "岩場", "natural=sand": "砂地",
    "landuse=forest": "森林", "landuse=farmland": "農地", "landuse=meadow": "牧草地",
    "landuse=residential": "住宅地", "landuse=grass": "草地", "landuse=orchard": "果樹園",
    "landuse=allotments": "市民農園", "landuse=cemetery": "墓地", "landuse=industrial": "工業地",
    "landuse=commercial": "商業地", "landuse=retail": "商業地", "landuse=recreation_ground": "公園",
    "landuse=village_green": "公園", "landuse=reservoir": "貯水池", "landuse=basin": "調整池",
    "landuse=paddy": "水田", "leisure=park": "公園", "leisure=garden": "庭園",
    "leisure=nature_reserve": "保護区",
}


def elevation(client: httpx.Client, latitude: float, longitude: float) -> float | None:
    try:
        response = client.get(ELEVATION_API, params={"lon": longitude, "lat": latitude, "outtype": "JSON"})
        value = response.json().get("elevation")
        return float(value) if isinstance(value, (int, float)) else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def surroundings(client: httpx.Client, latitude: float, longitude: float, radius: int = 300) -> list[str]:
    """周辺にある土地利用を、多い順に返す。"""
    query = (f"[out:json][timeout:25];("
             f"way(around:{radius},{latitude},{longitude})[landuse];"
             f"way(around:{radius},{latitude},{longitude})[natural];"
             f"way(around:{radius},{latitude},{longitude})[leisure];"
             f");out tags 40;")
    try:
        response = client.post(OVERPASS_API, data={"data": query})
        elements = response.json().get("elements", [])
    except (httpx.HTTPError, ValueError):
        return []
    counted: collections.Counter[str] = collections.Counter()
    for element in elements:
        tags = element.get("tags", {})
        for key in ("landuse", "natural", "leisure"):
            word = PLACE_WORDS.get(f"{key}={tags.get(key)}")
            if word:
                counted[word] += 1
    return [word for word, _ in counted.most_common(3)]


def main() -> int:
    data = json.loads(MANIFEST.read_text())
    entries = [e for e in data["entries"] if e.get("latitude") is not None]
    print(f"■ {len(entries)}件の座標に、標高と周辺の土地利用を足す")

    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        for index, entry in enumerate(entries, 1):
            latitude, longitude = entry["latitude"], entry["longitude"]
            entry["elevation"] = elevation(client, latitude, longitude)
            entry["surroundings"] = surroundings(client, latitude, longitude)
            if index % 10 == 0 or index == len(entries):
                print(f"  {index}/{len(entries)}", flush=True)
            time.sleep(1.2)      # 相手のサーバーを叩きすぎない

    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with_elevation = sum(1 for e in entries if e.get("elevation") is not None)
    with_place = sum(1 for e in entries if e.get("surroundings"))
    print(f"\n  標高が取れた: {with_elevation}件 / 周辺が分かった: {with_place}件")
    for entry in entries[:4]:
        print(f"    {entry['truth'].get('name', '?') if isinstance(entry['truth'], dict) else entry['truth']}"
              f"  標高 {entry.get('elevation')}m  {entry.get('surroundings')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
