"""国指定の重要無形民俗文化財を祭りに照合し、frontend/festivals.json の
cultural_relaw を補完する。

出典は Wikipedia「重要無形民俗文化財」の版固定スナップショット
(data/juyo-mukei-minzoku-bunkazai.json)。照合条件は次の両方を満たすこと。

- 祭りの wikipedia_title または label_ja が、指定名称中のリンク先記事名と
  一致する(リンクの無い指定は指定名称そのものと一致する)
- 祭りの prefecture が指定の都道府県見出しに含まれる

総称記事に結び付いた祭りは EXCLUDE で外し、名称が派生した重複項目は
INCLUDE で明示的に結ぶ。既存の url(文化庁 国指定文化財等データベースの
詳細ページ)は手で確認済みのため保持する。
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "juyo-mukei-minzoku-bunkazai.json"
FESTIVALS = ROOT / "frontend" / "festivals.json"
DESIGNATION = "重要無形民俗文化財"

PREFECTURES = (
    "北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 "
    "埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 "
    "岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 "
    "鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 "
    "佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県"
).split()
PREF_RE = re.compile("|".join(PREFECTURES))
ITEM_RE = re.compile(r"\*\s*(.+?)(★?)\s*（(\d{4})年(\d+)月(\d+)日")
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# 総称記事(各地にある芸能・行事の一般項目)で、特定の指定と同一視できないもの。
EXCLUDE = {
    "Q11676445",  # 鷺舞(総称。指定は津和野弥栄神社の鷺舞)
    "Q861941",    # ねぶた(総称。指定は青森のねぶた等)
}
# 名称の揺れで自動照合できないが、同一の指定と確認したもの。qid -> 指定名称
INCLUDE = {
    "Q11423431": "土崎神明社祭の曳山行事",
}


def parse_items(wikitext):
    items, prefs = [], []
    for line in wikitext.splitlines():
        if line.startswith(";"):
            prefs = PREF_RE.findall(line)
            continue
        m = ITEM_RE.match(line)
        if not m:
            continue
        namepart = m.group(1)
        targets = [x.split("|")[0].strip() for x in LINK_RE.findall(namepart)]
        name = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", namepart).strip()
        items.append({
            "name": name,
            "targets": targets,
            "prefectures": prefs,
            "unesco": bool(m.group(2)),
            "designated_date": f"{m.group(3)}-{int(m.group(4)):02d}-{int(m.group(5)):02d}",
        })
    return items


def match(festival, items):
    qid = festival.get("qid")
    if qid in EXCLUDE:
        return None
    if qid in INCLUDE:
        return next((it for it in items if it["name"] == INCLUDE[qid]), None)
    keys = {festival.get("wikipedia_title") or "", festival.get("label_ja") or ""} - {""}
    for it in items:
        if festival.get("prefecture") not in it["prefectures"]:
            continue
        if keys & set(it["targets"]) or it["name"] in keys:
            return it
    return None


def main():
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    items = parse_items(snap["wikitext"])
    data = json.loads(FESTIVALS.read_text(encoding="utf-8"))
    matched = 0
    for e in data:
        it = match(e, items)
        if not it:
            e.pop("cultural_relaw", None)
            continue
        url = (e.get("cultural_relaw") or {}).get("url") or ""
        e["cultural_relaw"] = {
            "cultural_type": DESIGNATION,
            "name": it["name"],
            "prefecture": e.get("prefecture") or "",
            "designated_date": it["designated_date"],
            "unesco": it["unesco"],
            "url": url,
            "source": snap["url"],
        }
        matched += 1
    FESTIVALS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"items={len(items)} matched={matched} with_url={sum(1 for e in data if (e.get('cultural_relaw') or {}).get('url'))}")


if __name__ == "__main__":
    main()
