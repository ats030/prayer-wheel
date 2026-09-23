#!/usr/bin/env python3
"""公式ページで確認した年次開催期間をライブデータへ反映する。"""

import argparse
import json
from pathlib import Path


VERIFIED_OCCURRENCES = {
    "Q11487199": [
        {"year": 2026, "start": "2026-04-10", "end": "2026-05-05", "source": "https://www.hirosakipark.jp/sakura/"},
    ],
    "Q11487200": [
        {"year": 2026, "start": "2026-08-01", "end": "2026-08-07", "source": "https://www.hirosaki-kanko.or.jp/web/edit.html?id=cat02_summer_neputa"},
    ],
    "Q1046742": [
        {"year": 2026, "start": "2026-12-29", "end": "2026-12-31", "status": "scheduled", "source": "https://www.comiket.co.jp/"},
    ],
    "Q1749262": [
        {"year": 2026, "start": "2026-07-01", "end": "2026-07-15", "source": "https://www.hakatayamakasa.com/"},
    ],
    "Q11261730": [
        {"year": 2026, "start": "2026-07-24", "end": "2026-07-26", "source": "https://otaru.ushiomatsuri.net/"},
    ],
    "Q11465749": [
        {"year": 2026, "start": "2026-01-24", "end": "2026-03-08", "source": "https://sounkyo.net/hyoubaku/"},
        {"year": 2027, "start": "2027-01-23", "end": "2027-03-07", "status": "scheduled", "source": "https://sounkyo.net/hyoubaku/"},
    ],
    "Q85869630": [
        {"year": 2026, "start": "2026-02-06", "end": "2026-02-08", "source": "https://tic.mombetsu.net/drift-ice-fes/"},
        {"year": 2027, "start": "2027-02-11", "end": "2027-02-14", "status": "scheduled", "source": "https://tic.mombetsu.net/drift-ice-fes/"},
    ],
    "Q118153386": [
        {"year": 2026, "start": "2026-10-31", "end": "2026-11-03", "status": "scheduled", "source": "https://toukiichi.mashiko-db.net/"},
    ],
    "Q11495708": [
        {"year": 2026, "start": "2026-07-10", "end": "2026-07-12", "source": "https://www.nrtk.jp/enjoy/shikisaisai/gion-festival.html"},
    ],
    "Q720663": [
        {"year": 2026, "start": "2026-08-29", "end": "2026-08-29", "source": "https://www.asakusa-samba.org/"},
    ],
    "Q11274533": [
        {"year": 2026, "start": "2026-08-05", "end": "2026-08-14", "source": "https://www.toukae.jp/"},
    ],
    "Q132860355": [
        {"year": 2026, "start": "2026-08-01", "end": "2026-08-01", "source": "https://matsudo-hanabi.com/"},
    ],
    "Q114712": [
        {"year": 2026, "start": "2026-10-07", "end": "2026-10-09", "status": "scheduled", "source": "https://nagasaki-kunchi.com/"},
    ],
    "Q4701224": [
        {"year": 2026, "start": "2026-08-03", "end": "2026-08-06", "source": "https://www.kantou.gr.jp/kanran/"},
    ],
    "Q9385159": [
        {"year": 2026, "start": "2026-08-06", "end": "2026-08-08", "source": "https://www.sendaitanabata.com/special/2951/"},
    ],
    "Q6663970": [
        {"year": 2026, "start": "2026-05-01", "end": "2026-05-01", "source": "https://www.takaoka.or.jp/news/detail_114.html"},
    ],
    "Q7398902": [
        {"year": 2026, "start": "2026-10-30", "end": "2026-11-03", "status": "scheduled", "source": "https://www.sibf.jp/news/2026/20260311a.html"},
    ],
    "Q6663968": [
        {"year": 2026, "start": "2026-05-30", "end": "2026-05-30", "source": "https://www.adachikanko.net/en/adachi_no_hanabi48"},
    ],
    "Q11413521": [
        {"year": 2026, "start": "2026-08-26", "end": "2026-08-27", "source": "https://www.city.fujiyoshida.yamanashi.jp/page/15160.html"},
    ],
    "Q493695": [
        {"year": 2026, "start": "2026-11-02", "end": "2026-11-04", "status": "scheduled", "source": "https://www.city.karatsu.lg.jp/page/4344.html"},
    ],
    "Q1043431": [
        {"year": 2026, "start": "2026-10-26", "end": "2026-11-04", "status": "scheduled", "source": "https://2026.tiff-jp.net/ja/"},
    ],
    "Q1151186": [
        {"year": 2026, "start": "2026-07-24", "end": "2026-07-26", "source": "https://www.fujirockfestival.com/info/index"},
    ],
    "Q11402392": [
        {"year": 2026, "start": "2026-08-09", "end": "2026-08-09", "source": "https://www.town.yoichi.hokkaido.jp/kankou/event/2026-0430-1416-19.html"},
    ],
}


def display_range(item):
    return item["start"] if item["start"] == item["end"] else f"{item['start']}〜{item['end']}"


def apply_occurrences(rows, verified=VERIFIED_OCCURRENCES):
    found = set()
    for row in rows:
        qid = row.get("qid")
        if qid not in verified:
            continue
        found.add(qid)
        by_key = {
            (item["year"], item["start"], item["end"]): item
            for item in row.get("occurrences", [])
        }
        for item in verified[qid]:
            by_key[(item["year"], item["start"], item["end"])] = item
        occurrences = sorted(by_key.values(), key=lambda item: item["start"])
        row["occurrences"] = occurrences
        row["date"] = display_range(occurrences[-1])
    missing = set(verified) - found
    if missing:
        raise ValueError(f"QID not found: {', '.join(sorted(missing))}")
    return rows


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "frontend/festivals.json")
    args = parser.parse_args()
    rows = json.loads(args.data.read_text(encoding="utf-8"))
    write_json(args.data, apply_occurrences(rows))
    print(f"verified occurrences applied: {len(VERIFIED_OCCURRENCES)} festivals")


if __name__ == "__main__":
    main()
