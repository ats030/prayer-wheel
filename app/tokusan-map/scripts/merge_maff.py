#!/usr/bin/env python3
"""Merge MAFF k_ryouri and traditional-foods candidates into official.json.

Rules enforced:
- label globally unique across official + curation-include + already-added set
- skip labels already present in official.json or curation.json(include)
- category: cuisine -> am/ry by name; traditional -> class mapping
- single prefecture-level coordinate reused from existing entries
"""
import json
import re
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TODAY = "2026-09-29"
AM_RE = re.compile(r"(餅|もち|だんご|団子|まんじゅう|饅頭)")
ING_JUNK = "ダウンロード可能な画像"

TRAD_CLASS = {
    "水産発発酵食品": "ui", "水産発酵食品": "ui", "その他水産加工品": "ui",
    "練り物": "ui", "海藻製品": "ui", "節類": "ui", "塩漬け": "ui", "くん製品": "ui",
    "穀類": "ko", "醤油、味噌、その他調味料": "ko", "豆類加工品": "ko",
    "飲料": "te", "菓子類": "am", "漬物": "ry", "その他農産加工品": "ry",
    "畜産加工品": "nk",
}
TRAD_BIG = {"農産": "sa2", "水産": "ui", "畜産": "nk", "その他": "ry"}
TRAD_CLASS_DEFAULT = "ry"


def clean(s):
    s = (s or "").split(ING_JUNK)[0]
    return re.sub(r"\s+", "", s).strip()


def main():
    official = json.loads((DATA / "official.json").read_text())
    curation = json.loads((DATA / "curation.json").read_text())
    wiki = {v["label"] for v in curation["include"].values()}
    used = {e["label"] for e in official} | wiki
    # a label with furigana parens collides with the bare-name entry (e.g. ニシン漬け（にしんづけ） vs ニシン漬け)
    used |= {re.sub(r"（.*?）", "", l) for l in used}

    def taken(label):
        return label in used or re.sub(r"（.*?）", "", label) in used

    # prefecture coordinates: first entry per prefecture (all prefecture_level)
    coords = {}
    for e in official:
        coords.setdefault(e["prefecture"], (e["lat"], e["lng"]))

    def entry(pref, label, prod_area, category, desc, url, kind, classification, ingredients):
        lat, lng = coords.get(pref, (0.0, 0.0))
        e = {
            "id": "local-" + uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:16],
            "label": label, "prefecture": pref, "place": pref,
            "lat": lat, "lng": lng, "prefecture_level": True,
            "production_area": clean(prod_area), "category": category,
            "description": desc, "source_name": "農林水産省", "source_url": url,
            "source_checked_at": TODAY, "source_kind": kind,
            "source_classification": clean(classification),
        }
        if ingredients:
            e["ingredients"] = clean(ingredients)
        return e

    added = 0
    k = json.loads((DATA / "k_ryouri_candidates.json").read_text())
    for x in k:
        pref, label = x["prefecture"], x["label"]
        if not x.get("ok") or taken(label):
            continue
        cat = "am" if AM_RE.search(label) else "ry"
        desc = f"{pref}に伝わる郷土料理。主な食材は{clean(x['ingredients'])}。"
        used.add(label)
        official.append(entry(pref, label, x["production_area"], cat, desc, x["url"], "cuisine", "", x["ingredients"]))
        added += 1

    t = json.loads((DATA / "traditional_candidates.json").read_text())
    for x in t:
        pref, label = x["prefecture"], x["label"]
        if not x.get("ok") or taken(label):
            continue
        cls_small = x.get("class_small", "")
        cat = TRAD_CLASS.get(cls_small)
        if cat is None:
            cat = TRAD_BIG.get(x.get("class_big", ""), TRAD_CLASS_DEFAULT)
        overview = clean(x.get("overview", ""))
        desc = f"{pref}の伝統食。" + (overview[:120] + "…" if len(overview) > 120 else overview)
        used.add(label)
        official.append(entry(pref, label, x["production_area"], cat, desc, x["url"], "traditional", x.get("class_small", ""), x["ingredients"]))
        added += 1

    (DATA / "official.json").write_text(json.dumps(official, ensure_ascii=False, indent=1) + "\n")

    # verification
    labels = [e["label"] for e in official]
    assert len(labels) == len(set(labels)), "label collision"
    from collections import Counter
    kinds = Counter(e["source_kind"] for e in official)
    print(f"added {added}; total {len(official)}")
    print(dict(kinds))
    print("sample new cuisine:", )


if __name__ == "__main__":
    main()
