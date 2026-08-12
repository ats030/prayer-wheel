"""既存のデータセットに、観察地点の座標と地名を足す。

「日本」という広さでは種を絞れなかった。沖縄と北海道では出る種が違うので、
座標なら効くかもしれない。それを測るために要る。

画像は取り直さない。観察IDから座標だけを引く。

  uv run --with httpx python eval/add_coordinates.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

MANIFEST = Path(__file__).parent / "dataset.json"
API = "https://api.inaturalist.org/v1/observations"
USER_AGENT = "IkimonoNote-eval/1.0 (https://github.com/ats030/ikimono-note)"


def fetch(observation_ids: list[int]) -> dict[int, dict]:
    """まとめて引く。1件ずつ叩くと 100回になり、相手に無用な負荷をかける。"""
    found: dict[int, dict] = {}
    with httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT}) as client:
        for start in range(0, len(observation_ids), 30):
            chunk = observation_ids[start:start + 30]
            response = client.get(f"{API}/{','.join(str(i) for i in chunk)}")
            response.raise_for_status()
            for result in response.json().get("results", []):
                found[result["id"]] = result
            time.sleep(1.0)      # 相手の様子を見ながら
    return found


def main() -> int:
    data = json.loads(MANIFEST.read_text())
    entries = data["entries"]
    observations = fetch([e["observation_id"] for e in entries])

    filled = obscured = missing = 0
    for entry in entries:
        result = observations.get(entry["observation_id"])
        if not result:
            missing += 1
            continue
        # 保護対象の種は、iNaturalist 側が座標をぼかして返す。その旨を残す
        entry["geoprivacy"] = result.get("taxon_geoprivacy") or result.get("geoprivacy") or ""
        entry["place_guess"] = result.get("place_guess") or ""
        # 時刻まで残す。夜行性か昼行性かは、ガとチョウのような紛らわしい相手を
        # 分ける手がかりになる。アプリは日付しか使っていないが、測るために取っておく
        entry["observed_on"] = (result.get("observed_on_details") or {}).get("date") or ""
        entry["observed_time"] = result.get("time_observed_at") or ""
        coords = result.get("geojson", {}).get("coordinates")
        if coords:
            entry["longitude"], entry["latitude"] = round(coords[0], 4), round(coords[1], 4)
            filled += 1
            if entry["geoprivacy"]:
                obscured += 1
        else:
            missing += 1

    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  座標あり: {filled} / {len(entries)}件")
    print(f"  うち、ぼかされたもの: {obscured}件（保護対象の種は正確な地点が出ない）")
    print(f"  取れなかったもの: {missing}件")
    places = [e.get("place_guess", "") for e in entries if e.get("place_guess")]
    print(f"  地名の例: {places[:2]}")
    dated = [e for e in entries if e.get("observed_on")]
    timed = [e for e in entries if e.get("observed_time")]
    print(f"  撮影日あり: {len(dated)}件 / 時刻あり: {len(timed)}件")
    if timed:
        print(f"  時刻の例: {[e['observed_time'] for e in timed[:2]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
