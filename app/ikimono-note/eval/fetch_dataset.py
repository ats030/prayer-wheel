"""iNaturalist の research-grade 観察から CC0 写真を集め、正解付き評価セットを作る。

ライセンス判断は ~/ai-workflow/tool-license-registry.yaml に記録済み (conditional)。
条件は「CC0 だけを使う」こと。photo_license=cc0 で絞るだけでなく、レスポンスの
license_code を1枚ずつ再検証し、cc0 以外は保存しない。

画像は再取得できるので ~/cache に置き、リポジトリにはマニフェストだけを残す。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import httpx

API = "https://api.inaturalist.org/v1/observations"
JAPAN_PLACE_ID = 6737
USER_AGENT = "IkimonoNote-eval/1.0 (https://github.com/ats030/ubuntu-server-app)"
CACHE_DIR = Path.home() / "cache" / "species-eval" / "images"
MANIFEST = Path(__file__).parent / "dataset.json"
ATTRIBUTION = (
    "iNaturalist Licensed Observation Images was accessed on {date} "
    "from https://registry.opendata.aws/inaturalist-open-data."
)

# 評価対象の分類群。アプリが扱う植物・動物を widely に散らす。
# iconic_taxa は iNaturalist の大分類。
GROUPS = {
    "植物": "Plantae",
    "昆虫": "Insecta",
    "鳥": "Aves",
    "菌類": "Fungi",
    "は虫類・両生類": "Reptilia,Amphibia",
}


# iNaturalist の写真サイズ。medium は長辺500pxで、アプリが外部AIへ送る上限
# (vision.MAX_EDGE=1600) に一度も届かない。つまり既存の結果はどれも、本番より
# 小さい写真での成績になっている。解像度の効き方を測るときは original を使う。
SIZE = os.getenv("IKIMONO_EVAL_PHOTO_SIZE", "medium")
if SIZE not in {"medium", "large", "original"}:
    raise SystemExit("IKIMONO_EVAL_PHOTO_SIZE は medium / large / original のいずれか")

def search(client: httpx.Client, iconic: str, per_group: int, place_id: int | None) -> list[dict]:
    """1グループぶんの観察を取る。取りこぼしを見越して多めに引く。"""
    params = {
        "quality_grade": "research",
        "photo_license": "cc0",
        "iconic_taxa": iconic,
        "rank": "species",
        "per_page": min(per_group * 4, 200),
        "order_by": "votes",
        "photos": "true",
        # 和名を返させる。アプリの表示も和名が主なので、評価の正解も和名で持つ
        "locale": "ja",
        "preferred_place_id": JAPAN_PLACE_ID,
    }
    if place_id:
        params["place_id"] = place_id
    response = client.get(API, params=params, timeout=30)
    response.raise_for_status()
    return response.json()["results"]


def pick(results: list[dict], group: str, want: int) -> list[dict]:
    chosen: list[dict] = []
    seen_taxa: set[int] = set()
    for observation in results:
        taxon = observation.get("taxon") or {}
        photos = observation.get("photos") or []
        if not photos or taxon.get("rank") != "species":
            continue
        # 同じ種ばかりにならないよう、1種1枚に限る
        if taxon["id"] in seen_taxa:
            continue
        photo = photos[0]
        # 条件の再検証。ここを緩めるとライセンス判断の前提が崩れる
        if photo.get("license_code") != "cc0":
            continue
        seen_taxa.add(taxon["id"])
        chosen.append({
            "group": group,
            "observation_id": observation["id"],
            "photo_id": photo["id"],
            "photo_url": photo["url"].replace("/square.", f"/{SIZE}."),
            "license_code": photo["license_code"],
            "attribution": photo.get("attribution", ""),
            "truth": {
                "taxon_id": taxon["id"],
                "name": taxon["name"],
                "rank": taxon["rank"],
                "common_name_ja": taxon.get("preferred_common_name") or "",
                "ancestry": taxon.get("ancestry", ""),
            },
        })
        if len(chosen) >= want:
            break
    return chosen


def download(client: httpx.Client, entries: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        target = CACHE_DIR / f"{entry['photo_id']}.jpg"
        entry["file"] = str(target)
        if target.exists():
            continue
        response = client.get(entry["photo_url"], timeout=60)
        response.raise_for_status()
        target.write_bytes(response.content)
        time.sleep(1)  # 推奨 60 req/分より十分低く保つ


def refetch(manifest: Path, output: Path, size: str, limit: int) -> int:
    """既存のマニフェストと同じ写真を、別の大きさで取り直す。

    解像度が効くかを測るには、種の顔ぶれを変えずに大きさだけ変えた組が要る。
    新しく取り直すと観察そのものが入れ替わり、何が効いたのか分からなくなる。
    """
    data = json.loads(manifest.read_text(encoding="utf-8"))
    entries = data["entries"][:limit] if limit else data["entries"]
    target_dir = CACHE_DIR.parent / f"images-{size}"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for index, entry in enumerate(entries, 1):
            fresh = dict(entry)
            fresh["photo_url"] = re.sub(r"/(square|small|medium|large|original)\.", f"/{size}.",
                                        entry["photo_url"])
            target = target_dir / f"{entry['photo_id']}.jpg"
            fresh["file"] = str(target)
            copied.append(fresh)
            if target.exists():
                continue
            response = client.get(fresh["photo_url"], timeout=120)
            response.raise_for_status()
            target.write_bytes(response.content)
            print(f"  {index:3}/{len(entries)} {target.name} {len(response.content)//1024}KB", flush=True)
            time.sleep(1)
    output.write_text(json.dumps({**data, "entries": copied,
                                  "license_note": data.get("license_note", "") + f" ({size})"},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(copied)}件 → {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refetch", default="", metavar="SIZE",
                        help="既存のマニフェストと同じ写真を、この大きさで取り直す (large / original)")
    parser.add_argument("--limit", type=int, default=0, help="--refetch のとき先頭N件だけ")
    parser.add_argument("--per-group", type=int, default=6, help="分類群ごとの枚数")
    parser.add_argument("--groups", nargs="*", default=list(GROUPS), choices=list(GROUPS),
                        help="取得する分類群。既定は全部")
    parser.add_argument("--output", default=str(MANIFEST), help="マニフェストの書き出し先")
    parser.add_argument("--place-id", type=int, default=JAPAN_PLACE_ID,
                        help="iNaturalist の場所ID。既定は日本 (6737)。0 で全世界")
    args = parser.parse_args()

    if args.refetch:
        return refetch(MANIFEST, Path(args.output) if args.output != str(MANIFEST)
                       else MANIFEST.with_name(f"dataset-{args.refetch}.json"),
                       args.refetch, args.limit)

    entries: list[dict] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for group in args.groups:
            iconic = GROUPS[group]
            results = search(client, iconic, args.per_group, args.place_id)
            picked = pick(results, group, args.per_group)
            print(f"{group:14} 候補 {len(results):3}件 → 採用 {len(picked)}件")
            entries.extend(picked)
            time.sleep(1)
        download(client, entries)

    non_cc0 = [e for e in entries if e["license_code"] != "cc0"]
    assert not non_cc0, f"CC0 以外が混入: {non_cc0}"

    pathlib_output = Path(args.output)
    pathlib_output.write_text(json.dumps({
        "source": "iNaturalist API v1 (quality_grade=research, photo_license=cc0)",
        "attribution": ATTRIBUTION.format(date=time.strftime("%Y-%m-%d")),
        "license_note": "全画像 CC0。画像は ~/cache/species-eval/images に置き、リポジトリへは含めない。",
        "place_id": args.place_id,
        "entries": entries,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n合計 {len(entries)}件 → {pathlib_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
